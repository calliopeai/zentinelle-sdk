package zentinelle

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

func TestRegisterUsesBootstrapHeaderAndSwapsRuntimeKey(t *testing.T) {
	t.Parallel()

	var (
		mu             sync.Mutex
		registerHeader http.Header
		evaluateHeader http.Header
	)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()

		switch r.URL.Path {
		case APIBasePath + "/register":
			registerHeader = r.Header.Clone()
			writeJSON(t, w, http.StatusCreated, map[string]interface{}{
				"agent_id": "agent-runtime",
				"api_key":  "sk_agent_runtime_key",
				"config":   map[string]interface{}{"heartbeat_interval_seconds": 60},
				"policies": []interface{}{},
			})
		case APIBasePath + "/evaluate":
			evaluateHeader = r.Header.Clone()
			writeJSON(t, w, http.StatusOK, map[string]interface{}{
				"allowed":            true,
				"reason":             "ok",
				"policies_evaluated": []interface{}{},
				"warnings":           []string{},
				"context":            map[string]interface{}{},
			})
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
	defer server.Close()

	client, err := NewClient(Config{
		APIKey:    "bt_tenant_signature",
		AgentType: "go-agent",
		Endpoint:  server.URL,
		FailOpen:  false,
	})
	if err != nil {
		t.Fatalf("NewClient() error = %v", err)
	}
	defer client.Shutdown()

	result, err := client.Register(context.Background(), RegisterOptions{Name: "Example"})
	if err != nil {
		t.Fatalf("Register() error = %v", err)
	}
	if result.AgentID != "agent-runtime" {
		t.Fatalf("Register() agent id = %q, want %q", result.AgentID, "agent-runtime")
	}
	if result.APIKey != "sk_agent_runtime_key" {
		t.Fatalf("Register() api key = %q, want %q", result.APIKey, "sk_agent_runtime_key")
	}

	if _, err := client.Evaluate(context.Background(), "tool_call", EvaluateOptions{
		UserID:  "user-1",
		Context: map[string]interface{}{"tool": "web_search"},
	}); err != nil {
		t.Fatalf("Evaluate() error = %v", err)
	}

	if got := registerHeader.Get("X-Zentinelle-Bootstrap"); got != "bt_tenant_signature" {
		t.Fatalf("register bootstrap header = %q, want bootstrap token", got)
	}
	if got := registerHeader.Get("X-Zentinelle-Key"); got != "" {
		t.Fatalf("register runtime key header = %q, want empty", got)
	}
	if got := evaluateHeader.Get("X-Zentinelle-Key"); got != "sk_agent_runtime_key" {
		t.Fatalf("evaluate runtime key header = %q, want %q", got, "sk_agent_runtime_key")
	}
}

func TestConfigSecretsAndHeartbeatUseCanonicalPaths(t *testing.T) {
	t.Parallel()

	var (
		mu    sync.Mutex
		paths []string
		auths []string
	)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		paths = append(paths, r.URL.Path)
		auths = append(auths, r.Header.Get("X-Zentinelle-Key"))
		mu.Unlock()

		switch r.URL.Path {
		case APIBasePath + "/config/agent-123":
			writeJSON(t, w, http.StatusOK, map[string]interface{}{
				"agent_id": "agent-123",
				"config":   map[string]interface{}{"mode": "strict"},
				"policies": []map[string]interface{}{
					{
						"id":          "policy-1",
						"name":        "No PII",
						"type":        "pii_filter",
						"enforcement": "enforce",
						"config":      map[string]interface{}{"redact": true},
					},
				},
				"updated_at": "2026-04-10T00:00:00Z",
			})
		case APIBasePath + "/secrets/agent-123":
			writeJSON(t, w, http.StatusOK, map[string]interface{}{
				"secrets": map[string]string{"OPENAI_API_KEY": "secret-value"},
			})
		case APIBasePath + "/heartbeat":
			writeJSON(t, w, http.StatusAccepted, map[string]interface{}{
				"acknowledged":           true,
				"config_changed":         true,
				"next_heartbeat_seconds": 30,
			})
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
	defer server.Close()

	client, err := NewClient(Config{
		APIKey:    "sk_agent_runtime_key",
		AgentType: "go-agent",
		AgentID:   "agent-123",
		Endpoint:  server.URL,
		FailOpen:  false,
	})
	if err != nil {
		t.Fatalf("NewClient() error = %v", err)
	}
	defer client.Shutdown()

	client.stateMu.Lock()
	client.registered = true
	client.stateMu.Unlock()

	config, err := client.GetConfig(context.Background())
	if err != nil {
		t.Fatalf("GetConfig() error = %v", err)
	}
	if config.AgentID != "agent-123" {
		t.Fatalf("GetConfig() agent id = %q, want %q", config.AgentID, "agent-123")
	}
	if got := config.Config["mode"]; got != "strict" {
		t.Fatalf("GetConfig() config[mode] = %v, want %q", got, "strict")
	}

	secrets, err := client.GetSecrets(context.Background())
	if err != nil {
		t.Fatalf("GetSecrets() error = %v", err)
	}
	if got := secrets["OPENAI_API_KEY"]; got != "secret-value" {
		t.Fatalf("GetSecrets() OPENAI_API_KEY = %q, want %q", got, "secret-value")
	}

	heartbeat, err := client.Heartbeat(context.Background(), "healthy", map[string]interface{}{"queue_depth": 5})
	if err != nil {
		t.Fatalf("Heartbeat() error = %v", err)
	}
	if heartbeat == nil || !heartbeat.Acknowledged || !heartbeat.ConfigChanged || heartbeat.NextHeartbeatSeconds != 30 {
		t.Fatalf("Heartbeat() = %#v, want acknowledged/config_changed/30", heartbeat)
	}

	wantPaths := []string{
		APIBasePath + "/config/agent-123",
		APIBasePath + "/secrets/agent-123",
		APIBasePath + "/heartbeat",
	}

	mu.Lock()
	defer mu.Unlock()
	if strings.Join(paths, ",") != strings.Join(wantPaths, ",") {
		t.Fatalf("paths = %v, want %v", paths, wantPaths)
	}
	for _, auth := range auths {
		if auth != "sk_agent_runtime_key" {
			t.Fatalf("auth header = %q, want runtime key", auth)
		}
	}
}

func writeJSON(t *testing.T, w http.ResponseWriter, status int, payload map[string]interface{}) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		t.Fatalf("json encode failed: %v", err)
	}
}
