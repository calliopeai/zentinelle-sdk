// Package zentinelle provides a Go client for AI agent governance.
//
// Zentinelle enables policy enforcement, secrets management, and observability
// for AI agents across any framework.
//
// Example usage:
//
//	client, err := zentinelle.NewClient(zentinelle.Config{
//		APIKey:    "sk_agent_...",
//		AgentType: "go-agent",
//	})
//	if err != nil {
//		log.Fatal(err)
//	}
//	defer client.Shutdown()
//
//	// Register on startup
//	result, err := client.Register(ctx, zentinelle.RegisterOptions{
//		Capabilities: []string{"chat", "tools"},
//	})
//
//	// Evaluate policies
//	eval, err := client.Evaluate(ctx, "tool_call", zentinelle.EvaluateOptions{
//		UserID:  "user123",
//		Context: map[string]interface{}{"tool": "web_search"},
//	})
//	if !eval.Allowed {
//		return fmt.Errorf("blocked: %s", eval.Reason)
//	}
package zentinelle

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"
)

const (
	DefaultEndpoint      = "https://api.zentinelle.ai"
	DefaultTimeout       = 30 * time.Second
	DefaultBufferSize    = 100
	DefaultFlushInterval = 5 * time.Second
)

// Config holds client configuration.
type Config struct {
	APIKey                  string
	AgentType               string
	Endpoint                string
	AgentID                 string
	OrgID                   string
	Timeout                 time.Duration
	MaxRetries              int
	FailOpen                bool
	BufferSize              int
	FlushInterval           time.Duration
	CircuitBreakerThreshold int
	CircuitBreakerTimeout   time.Duration
}

// Client is the Zentinelle SDK client.
type Client struct {
	config         Config
	httpClient     *http.Client
	agentID        string
	registered     bool
	eventBuffer    []Event
	bufferMu       sync.Mutex
	circuitBreaker *CircuitBreaker
	stopCh         chan struct{}
	wg             sync.WaitGroup
}

// NewClient creates a new Zentinelle client.
func NewClient(config Config) (*Client, error) {
	if config.APIKey == "" {
		return nil, fmt.Errorf("APIKey is required")
	}
	if config.AgentType == "" {
		return nil, fmt.Errorf("AgentType is required")
	}

	if config.Endpoint == "" {
		config.Endpoint = DefaultEndpoint
	}
	if config.Timeout == 0 {
		config.Timeout = DefaultTimeout
	}
	if config.MaxRetries == 0 {
		config.MaxRetries = 3
	}
	if config.BufferSize == 0 {
		config.BufferSize = DefaultBufferSize
	}
	if config.FlushInterval == 0 {
		config.FlushInterval = DefaultFlushInterval
	}
	if config.CircuitBreakerThreshold == 0 {
		config.CircuitBreakerThreshold = 5
	}
	if config.CircuitBreakerTimeout == 0 {
		config.CircuitBreakerTimeout = 30 * time.Second
	}

	c := &Client{
		config: config,
		httpClient: &http.Client{
			Timeout: config.Timeout,
		},
		agentID:        config.AgentID,
		eventBuffer:    make([]Event, 0, config.BufferSize),
		circuitBreaker: NewCircuitBreaker(config.CircuitBreakerThreshold, config.CircuitBreakerTimeout),
		stopCh:         make(chan struct{}),
	}

	// Start background flush goroutine
	c.wg.Add(1)
	go c.flushLoop()

	return c, nil
}

// flushLoop periodically flushes events.
func (c *Client) flushLoop() {
	defer c.wg.Done()
	ticker := time.NewTicker(c.config.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			if c.registered {
				_ = c.FlushEvents(context.Background())
			}
		case <-c.stopCh:
			return
		}
	}
}

// request makes an HTTP request with retry logic.
func (c *Client) request(ctx context.Context, method, path string, body interface{}) ([]byte, error) {
	if !c.circuitBreaker.CanExecute() {
		if c.config.FailOpen {
			return []byte("{}"), nil
		}
		return nil, &ConnectionError{Message: "circuit breaker is open"}
	}

	var bodyReader io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		bodyReader = bytes.NewReader(data)
	}

	url := c.config.Endpoint + "/api/v1" + path

	var lastErr error
	for attempt := 0; attempt <= c.config.MaxRetries; attempt++ {
		req, err := http.NewRequestWithContext(ctx, method, url, bodyReader)
		if err != nil {
			return nil, err
		}

		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("User-Agent", "zentinelle-go/0.1.0")
		req.Header.Set("X-Zentinelle-Key", c.config.APIKey)
		if c.config.OrgID != "" {
			req.Header.Set("X-Zentinelle-Org", c.config.OrgID)
		}

		resp, err := c.httpClient.Do(req)
		if err != nil {
			lastErr = err
			c.circuitBreaker.RecordFailure()
			if attempt < c.config.MaxRetries {
				time.Sleep(c.backoffDelay(attempt))
				continue
			}
			break
		}
		defer resp.Body.Close()

		respBody, err := io.ReadAll(resp.Body)
		if err != nil {
			lastErr = err
			continue
		}

		switch resp.StatusCode {
		case http.StatusOK, http.StatusCreated:
			c.circuitBreaker.RecordSuccess()
			return respBody, nil
		case http.StatusUnauthorized:
			return nil, &AuthError{Message: "invalid or expired API key"}
		case http.StatusForbidden:
			return nil, &AuthError{Message: "access denied"}
		case http.StatusTooManyRequests:
			retryAfter := 60
			c.circuitBreaker.RecordSuccess() // Rate limit isn't a failure
			return nil, &RateLimitError{Message: "rate limit exceeded", RetryAfter: retryAfter}
		default:
			if resp.StatusCode >= 500 {
				lastErr = &ConnectionError{Message: fmt.Sprintf("server error: %d", resp.StatusCode)}
				c.circuitBreaker.RecordFailure()
				if attempt < c.config.MaxRetries {
					time.Sleep(c.backoffDelay(attempt))
					continue
				}
			} else {
				return nil, fmt.Errorf("request failed: %d - %s", resp.StatusCode, string(respBody))
			}
		}
	}

	if c.config.FailOpen {
		return []byte("{}"), nil
	}
	return nil, lastErr
}

func (c *Client) backoffDelay(attempt int) time.Duration {
	delay := time.Duration(1<<uint(attempt)) * time.Second
	if delay > 60*time.Second {
		delay = 60 * time.Second
	}
	return delay
}

// RegisterOptions holds options for agent registration.
type RegisterOptions struct {
	Capabilities []string
	Metadata     map[string]interface{}
	Name         string
}

// RegisterResult holds the result of agent registration.
type RegisterResult struct {
	AgentID  string
	APIKey   string
	Config   map[string]interface{}
	Policies []PolicyConfig
}

// Register registers the agent with Zentinelle.
func (c *Client) Register(ctx context.Context, opts RegisterOptions) (*RegisterResult, error) {
	body := map[string]interface{}{
		"agent_id":     c.agentID,
		"agent_type":   c.config.AgentType,
		"capabilities": opts.Capabilities,
		"metadata":     opts.Metadata,
		"name":         opts.Name,
	}

	resp, err := c.request(ctx, http.MethodPost, "/agents/register", body)
	if err != nil {
		return nil, err
	}

	var result struct {
		AgentID  string                   `json:"agent_id"`
		APIKey   string                   `json:"api_key"`
		Config   map[string]interface{}   `json:"config"`
		Policies []map[string]interface{} `json:"policies"`
	}
	if err := json.Unmarshal(resp, &result); err != nil {
		return nil, err
	}

	c.agentID = result.AgentID
	c.registered = true

	policies := make([]PolicyConfig, len(result.Policies))
	for i, p := range result.Policies {
		policies[i] = PolicyConfig{
			ID:          getString(p, "id"),
			Name:        getString(p, "name"),
			Type:        getString(p, "type"),
			Enforcement: getString(p, "enforcement"),
			Config:      getMap(p, "config"),
		}
	}

	return &RegisterResult{
		AgentID:  result.AgentID,
		APIKey:   result.APIKey,
		Config:   result.Config,
		Policies: policies,
	}, nil
}

// EvaluateOptions holds options for policy evaluation.
type EvaluateOptions struct {
	UserID  string
	Context map[string]interface{}
}

// EvaluateResult holds the result of policy evaluation.
type EvaluateResult struct {
	Allowed           bool
	Reason            string
	PoliciesEvaluated []PolicyEvaluation
	Warnings          []string
	Context           map[string]interface{}
}

// PolicyEvaluation holds the result of a single policy evaluation.
type PolicyEvaluation struct {
	Name    string
	Type    string
	Passed  bool
	Message string
}

// Evaluate evaluates policies for an action.
func (c *Client) Evaluate(ctx context.Context, action string, opts EvaluateOptions) (*EvaluateResult, error) {
	body := map[string]interface{}{
		"agent_id": c.agentID,
		"action":   action,
		"user_id":  opts.UserID,
		"context":  opts.Context,
	}

	resp, err := c.request(ctx, http.MethodPost, "/evaluate", body)
	if err != nil {
		return nil, err
	}

	var result struct {
		Allowed           bool                     `json:"allowed"`
		Reason            string                   `json:"reason"`
		PoliciesEvaluated []map[string]interface{} `json:"policies_evaluated"`
		Warnings          []string                 `json:"warnings"`
		Context           map[string]interface{}   `json:"context"`
	}
	if err := json.Unmarshal(resp, &result); err != nil {
		return nil, err
	}

	policies := make([]PolicyEvaluation, len(result.PoliciesEvaluated))
	for i, p := range result.PoliciesEvaluated {
		policies[i] = PolicyEvaluation{
			Name:    getString(p, "name"),
			Type:    getString(p, "type"),
			Passed:  getBool(p, "passed"),
			Message: getString(p, "message"),
		}
	}

	return &EvaluateResult{
		Allowed:           result.Allowed,
		Reason:            result.Reason,
		PoliciesEvaluated: policies,
		Warnings:          result.Warnings,
		Context:           result.Context,
	}, nil
}

// CanCallTool checks if a tool can be called.
func (c *Client) CanCallTool(ctx context.Context, toolName string, userID string) (*EvaluateResult, error) {
	return c.Evaluate(ctx, "tool_call", EvaluateOptions{
		UserID:  userID,
		Context: map[string]interface{}{"tool": toolName},
	})
}

// CanUseModel checks if a model can be used.
func (c *Client) CanUseModel(ctx context.Context, model, provider string) (*EvaluateResult, error) {
	return c.Evaluate(ctx, "model_request", EvaluateOptions{
		Context: map[string]interface{}{"model": model, "provider": provider},
	})
}

// GetSecrets retrieves secrets for the agent.
func (c *Client) GetSecrets(ctx context.Context) (map[string]string, error) {
	resp, err := c.request(ctx, http.MethodGet, "/agents/"+c.agentID+"/secrets", nil)
	if err != nil {
		return nil, err
	}

	var result struct {
		Secrets map[string]string `json:"secrets"`
	}
	if err := json.Unmarshal(resp, &result); err != nil {
		return nil, err
	}

	return result.Secrets, nil
}

// TrackUsage tracks model usage for cost policies.
func (c *Client) TrackUsage(usage ModelUsage) {
	c.Emit("model_usage", map[string]interface{}{
		"provider":       usage.Provider,
		"model":          usage.Model,
		"input_tokens":   usage.InputTokens,
		"output_tokens":  usage.OutputTokens,
		"estimated_cost": usage.EstimatedCost,
	}, EmitOptions{Category: "telemetry"})
}

// EmitOptions holds options for event emission.
type EmitOptions struct {
	Category string
	UserID   string
}

// Emit emits an event (buffered).
func (c *Client) Emit(eventType string, payload map[string]interface{}, opts EmitOptions) {
	category := opts.Category
	if category == "" {
		category = "telemetry"
	}

	event := Event{
		Type:      eventType,
		Category:  category,
		Payload:   payload,
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		UserID:    opts.UserID,
	}

	c.bufferMu.Lock()
	c.eventBuffer = append(c.eventBuffer, event)
	shouldFlush := len(c.eventBuffer) >= c.config.BufferSize
	c.bufferMu.Unlock()

	if shouldFlush {
		go func() {
			_ = c.FlushEvents(context.Background())
		}()
	}
}

// EmitToolCall emits a tool call event.
func (c *Client) EmitToolCall(toolName string, userID string, durationMs int64) {
	c.Emit("tool_call", map[string]interface{}{
		"tool":        toolName,
		"duration_ms": durationMs,
	}, EmitOptions{Category: "audit", UserID: userID})
}

// FlushEvents flushes buffered events.
func (c *Client) FlushEvents(ctx context.Context) error {
	c.bufferMu.Lock()
	if len(c.eventBuffer) == 0 || c.agentID == "" {
		c.bufferMu.Unlock()
		return nil
	}
	events := c.eventBuffer
	c.eventBuffer = make([]Event, 0, c.config.BufferSize)
	c.bufferMu.Unlock()

	body := map[string]interface{}{
		"agent_id": c.agentID,
		"events":   events,
	}

	_, err := c.request(ctx, http.MethodPost, "/events", body)
	if err != nil {
		// Re-queue events on failure
		c.bufferMu.Lock()
		if len(c.eventBuffer) < c.config.BufferSize*2 {
			c.eventBuffer = append(events, c.eventBuffer...)
		}
		c.bufferMu.Unlock()
		return err
	}

	return nil
}

// Heartbeat sends a heartbeat.
func (c *Client) Heartbeat(ctx context.Context, status string, metrics map[string]interface{}) error {
	if !c.registered || c.agentID == "" {
		return nil
	}

	body := map[string]interface{}{
		"agent_id": c.agentID,
		"status":   status,
		"metrics":  metrics,
	}

	_, err := c.request(ctx, http.MethodPost, "/heartbeat", body)
	return err
}

// Shutdown gracefully shuts down the client.
func (c *Client) Shutdown() {
	close(c.stopCh)
	c.wg.Wait()
	_ = c.FlushEvents(context.Background())
}

// AgentID returns the current agent ID.
func (c *Client) AgentID() string {
	return c.agentID
}

// IsRegistered returns whether the agent is registered.
func (c *Client) IsRegistered() bool {
	return c.registered
}

// Helper functions
func getString(m map[string]interface{}, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func getBool(m map[string]interface{}, key string) bool {
	if v, ok := m[key].(bool); ok {
		return v
	}
	return false
}

func getMap(m map[string]interface{}, key string) map[string]interface{} {
	if v, ok := m[key].(map[string]interface{}); ok {
		return v
	}
	return nil
}
