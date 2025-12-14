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
	"log"
	"math/rand"
	"net/http"
	"strings"
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
	SecretsCacheTTL         time.Duration // TTL for secrets cache (default: 60s)
	ConfigCacheTTL          time.Duration // TTL for config cache (default: 300s)
}

// Client is the Zentinelle SDK client.
type Client struct {
	config         Config
	httpClient     *http.Client
	agentID        string
	registered     bool
	eventBuffer    []Event
	maxBufferSize  int // Maximum buffer size to prevent memory leaks
	bufferMu       sync.Mutex
	stateMu        sync.RWMutex // Protects agentID and registered
	circuitBreaker *CircuitBreaker
	stopCh         chan struct{}
	stopOnce       sync.Once // Ensures Shutdown only runs once
	wg             sync.WaitGroup

	// Caches
	secretsCache     map[string]string
	secretsCacheTime time.Time
	secretsCacheMu   sync.RWMutex
	configCache      map[string]interface{}
	configCacheTime  time.Time
	configCacheMu    sync.RWMutex
}

// NewClient creates a new Zentinelle client.
func NewClient(config Config) (*Client, error) {
	if config.APIKey == "" {
		return nil, fmt.Errorf("APIKey is required")
	}
	// Validate API key format (should start with sk_agent_)
	if len(config.APIKey) < 10 {
		return nil, fmt.Errorf("APIKey format is invalid")
	}
	// Validate API key format (should start with known prefixes)
	validPrefixes := []string{"sk_agent_", "sk_test_", "sk_live_", "znt_"}
	hasValidPrefix := false
	for _, prefix := range validPrefixes {
		if strings.HasPrefix(config.APIKey, prefix) {
			hasValidPrefix = true
			break
		}
	}
	if !hasValidPrefix {
		log.Printf("[Zentinelle] API key does not match expected format (sk_agent_*, sk_test_*, sk_live_*, znt_*). This may indicate an invalid key.")
	}
	if config.AgentType == "" {
		return nil, fmt.Errorf("AgentType is required")
	}

	if config.Endpoint == "" {
		config.Endpoint = DefaultEndpoint
	}

	// Enforce HTTPS for security (API keys are transmitted in headers)
	if !strings.HasPrefix(config.Endpoint, "https://") {
		return nil, fmt.Errorf("endpoint must use HTTPS for security")
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
	if config.SecretsCacheTTL == 0 {
		config.SecretsCacheTTL = 60 * time.Second
	}
	if config.ConfigCacheTTL == 0 {
		config.ConfigCacheTTL = 300 * time.Second
	}

	// Calculate max buffer size (10x normal or 1000, whichever is larger)
	maxBufferSize := config.BufferSize * 10
	if maxBufferSize < 1000 {
		maxBufferSize = 1000
	}

	c := &Client{
		config: config,
		httpClient: &http.Client{
			Timeout: config.Timeout,
		},
		agentID:        config.AgentID,
		eventBuffer:    make([]Event, 0, config.BufferSize),
		maxBufferSize:  maxBufferSize,
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
			c.stateMu.RLock()
			registered := c.registered
			c.stateMu.RUnlock()
			if registered {
				if err := c.FlushEvents(context.Background()); err != nil {
					log.Printf("[Zentinelle] Background event flush failed: %v", err)
				}
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

	// Marshal body once and reuse for retries
	var bodyData []byte
	if body != nil {
		var err error
		bodyData, err = json.Marshal(body)
		if err != nil {
			return nil, err
		}
	}

	url := c.config.Endpoint + "/api/v1" + path

	var lastErr error
	for attempt := 0; attempt <= c.config.MaxRetries; attempt++ {
		// Create a fresh reader for each attempt to avoid EOF issues
		var bodyReader io.Reader
		if bodyData != nil {
			bodyReader = bytes.NewReader(bodyData)
		}

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

		respBody, err := io.ReadAll(resp.Body)
		resp.Body.Close() // Close immediately, not defer (avoid leak in retry loop)
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
	// Add jitter (±25%) to prevent thundering herd
	jitterRange := float64(delay) * 0.25
	jitter := time.Duration((rand.Float64()*2 - 1) * jitterRange)
	delay += jitter
	if delay < 0 {
		delay = 0
	}
	return delay
}

// requestForEvaluate makes an HTTP request with proper fail-open handling for evaluate.
func (c *Client) requestForEvaluate(ctx context.Context, method, path string, body interface{}) ([]byte, bool, error) {
	if !c.circuitBreaker.CanExecute() {
		if c.config.FailOpen {
			log.Printf("[Zentinelle] Circuit breaker OPEN, failing open for evaluate request")
			return c.createFailOpenEvaluateResponse(), true, nil
		}
		return nil, false, &ConnectionError{Message: "circuit breaker is open"}
	}

	resp, err := c.request(ctx, method, path, body)
	if err != nil {
		if c.config.FailOpen {
			if _, ok := err.(*ConnectionError); ok {
				log.Printf("[Zentinelle] Request failed, failing open: %v", err)
				return c.createFailOpenEvaluateResponse(), true, nil
			}
		}
		return nil, false, err
	}
	return resp, false, nil
}

// createFailOpenEvaluateResponse creates a proper fail-open response for evaluate.
func (c *Client) createFailOpenEvaluateResponse() []byte {
	response := map[string]interface{}{
		"allowed":            true,
		"reason":             "fail_open",
		"fail_open":          true,
		"policies_evaluated": []interface{}{},
		"warnings":           []string{"Service unavailable - fail-open mode active"},
		"context":            map[string]interface{}{},
	}
	data, _ := json.Marshal(response)
	return data
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

	c.stateMu.Lock()
	c.agentID = result.AgentID
	c.registered = true
	c.stateMu.Unlock()

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
	FailOpen          bool // True if result was returned due to fail-open mode
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
	// Get agentID under lock to prevent data race
	c.stateMu.RLock()
	agentID := c.agentID
	c.stateMu.RUnlock()

	body := map[string]interface{}{
		"agent_id": agentID,
		"action":   action,
		"user_id":  opts.UserID,
		"context":  opts.Context,
	}

	resp, isFailOpen, err := c.requestForEvaluate(ctx, http.MethodPost, "/evaluate", body)
	if err != nil {
		return nil, err
	}

	// Parse into raw map first to validate 'allowed' field exists
	var rawResult map[string]interface{}
	if err := json.Unmarshal(resp, &rawResult); err != nil {
		return nil, err
	}

	// Check for fail-open response
	failOpen := getBool(rawResult, "fail_open") || isFailOpen

	// Critical: validate that 'allowed' field is present (unless fail-open)
	// Never default to true - this would bypass security
	if !failOpen {
		if _, hasAllowed := rawResult["allowed"]; !hasAllowed {
			return nil, &Error{Message: "invalid response: missing required 'allowed' field"}
		}
	}

	var result struct {
		Allowed           bool                     `json:"allowed"`
		Reason            string                   `json:"reason"`
		PoliciesEvaluated []map[string]interface{} `json:"policies_evaluated"`
		Warnings          []string                 `json:"warnings"`
		Context           map[string]interface{}   `json:"context"`
		FailOpen          bool                     `json:"fail_open"`
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
		FailOpen:          failOpen,
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
	return c.GetSecretsWithRefresh(ctx, false)
}

// GetSecretsWithRefresh retrieves secrets with optional cache bypass.
func (c *Client) GetSecretsWithRefresh(ctx context.Context, forceRefresh bool) (map[string]string, error) {
	// Check cache first
	if !forceRefresh {
		c.secretsCacheMu.RLock()
		if c.secretsCache != nil && time.Since(c.secretsCacheTime) < c.config.SecretsCacheTTL {
			// Return a copy to prevent modification
			secrets := make(map[string]string, len(c.secretsCache))
			for k, v := range c.secretsCache {
				secrets[k] = v
			}
			c.secretsCacheMu.RUnlock()
			return secrets, nil
		}
		c.secretsCacheMu.RUnlock()
	}

	// Get agentID under lock to prevent data race
	c.stateMu.RLock()
	agentID := c.agentID
	c.stateMu.RUnlock()

	if agentID == "" {
		return nil, fmt.Errorf("agent not registered")
	}

	// Fetch fresh secrets
	resp, err := c.request(ctx, http.MethodGet, "/agents/"+agentID+"/secrets", nil)
	if err != nil {
		return nil, err
	}

	var result struct {
		Secrets map[string]string `json:"secrets"`
	}
	if err := json.Unmarshal(resp, &result); err != nil {
		return nil, err
	}

	// Update cache and return a copy to prevent caller modification corrupting cache
	c.secretsCacheMu.Lock()
	c.secretsCache = result.Secrets
	c.secretsCacheTime = time.Now()
	// Return a copy to prevent modification
	secrets := make(map[string]string, len(c.secretsCache))
	for k, v := range c.secretsCache {
		secrets[k] = v
	}
	c.secretsCacheMu.Unlock()

	return secrets, nil
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
	// Enforce max buffer size to prevent memory leaks
	if len(c.eventBuffer) >= c.maxBufferSize {
		dropped := len(c.eventBuffer) - c.maxBufferSize + 1
		c.eventBuffer = c.eventBuffer[dropped:]
		log.Printf("[Zentinelle] Event buffer at max capacity, dropped %d oldest events", dropped)
	}
	c.eventBuffer = append(c.eventBuffer, event)
	c.bufferMu.Unlock()

	// Note: Flushing is handled by the background flushLoop goroutine.
	// We don't spawn additional goroutines here to avoid goroutine leaks.
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
	c.stateMu.RLock()
	agentID := c.agentID
	c.stateMu.RUnlock()

	c.bufferMu.Lock()
	if len(c.eventBuffer) == 0 || agentID == "" {
		c.bufferMu.Unlock()
		return nil
	}
	events := c.eventBuffer
	c.eventBuffer = make([]Event, 0, c.config.BufferSize)
	c.bufferMu.Unlock()

	body := map[string]interface{}{
		"agent_id": agentID,
		"events":   events,
	}

	_, err := c.request(ctx, http.MethodPost, "/events", body)
	if err != nil {
		// Re-queue events on failure (check against maxBufferSize to avoid overflow)
		c.bufferMu.Lock()
		if len(c.eventBuffer)+len(events) <= c.maxBufferSize {
			c.eventBuffer = append(events, c.eventBuffer...)
		} else {
			log.Printf("[Zentinelle] Failed to flush %d events and buffer is full, events dropped", len(events))
		}
		c.bufferMu.Unlock()
		return err
	}

	return nil
}

// Heartbeat sends a heartbeat.
func (c *Client) Heartbeat(ctx context.Context, status string, metrics map[string]interface{}) error {
	c.stateMu.RLock()
	registered := c.registered
	agentID := c.agentID
	c.stateMu.RUnlock()

	if !registered || agentID == "" {
		return nil
	}

	body := map[string]interface{}{
		"agent_id": agentID,
		"status":   status,
		"metrics":  metrics,
	}

	_, err := c.request(ctx, http.MethodPost, "/heartbeat", body)
	return err
}

// Shutdown gracefully shuts down the client.
// Safe to call multiple times.
func (c *Client) Shutdown() {
	c.stopOnce.Do(func() {
		close(c.stopCh)
		c.wg.Wait()
		// Final flush with timeout to avoid hanging
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := c.FlushEvents(ctx); err != nil {
			log.Printf("[Zentinelle] Failed to flush events during shutdown: %v", err)
		}
	})
}

// AgentID returns the current agent ID.
func (c *Client) AgentID() string {
	c.stateMu.RLock()
	defer c.stateMu.RUnlock()
	return c.agentID
}

// IsRegistered returns whether the agent is registered.
func (c *Client) IsRegistered() bool {
	c.stateMu.RLock()
	defer c.stateMu.RUnlock()
	return c.registered
}

// String returns a string representation of the client with masked API key.
func (c *Client) String() string {
	maskedKey := "***"
	if len(c.config.APIKey) > 12 {
		maskedKey = c.config.APIKey[:8] + "..." + c.config.APIKey[len(c.config.APIKey)-4:]
	}
	c.stateMu.RLock()
	agentID := c.agentID
	c.stateMu.RUnlock()
	return fmt.Sprintf("ZentinelleClient(agent_id=%q, agent_type=%q, endpoint=%q, api_key=%q)",
		agentID, c.config.AgentType, c.config.Endpoint, maskedKey)
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
