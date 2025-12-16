package zentinelle

// PolicyType represents a policy type.
type PolicyType string

const (
	PolicyTypeRateLimit       PolicyType = "rate_limit"
	PolicyTypeCostLimit       PolicyType = "cost_limit"
	PolicyTypePIIFilter       PolicyType = "pii_filter"
	PolicyTypePromptInjection PolicyType = "prompt_injection"
	PolicyTypeSystemPrompt    PolicyType = "system_prompt"
	PolicyTypeModelRestrict   PolicyType = "model_restriction"
	PolicyTypeHumanOversight  PolicyType = "human_oversight"
	PolicyTypeAgentCapability PolicyType = "agent_capability"
	PolicyTypeAgentMemory     PolicyType = "agent_memory"
	PolicyTypeDataRetention   PolicyType = "data_retention"
	PolicyTypeAuditLog        PolicyType = "audit_log"
)

// Enforcement represents a policy enforcement level.
type Enforcement string

const (
	EnforcementEnforce  Enforcement = "enforce"
	EnforcementWarn     Enforcement = "warn"
	EnforcementLog      Enforcement = "log"
	EnforcementDisabled Enforcement = "disabled"
)

// EventCategory represents an event category.
type EventCategory string

const (
	EventCategoryTelemetry  EventCategory = "telemetry"
	EventCategoryAudit      EventCategory = "audit"
	EventCategoryAlert      EventCategory = "alert"
	EventCategoryCompliance EventCategory = "compliance"
)

// PolicyConfig represents a policy configuration.
type PolicyConfig struct {
	ID          string
	Name        string
	Type        string
	Enforcement string
	Config      map[string]interface{}
	Priority    int
}

// Event represents a telemetry event.
type Event struct {
	Type      string                 `json:"type"`
	Category  string                 `json:"category"`
	Payload   map[string]interface{} `json:"payload"`
	Timestamp string                 `json:"timestamp"`
	UserID    string                 `json:"user_id,omitempty"`
}

// ModelUsage represents model usage for cost tracking.
type ModelUsage struct {
	Provider      string
	Model         string
	InputTokens   int
	OutputTokens  int
	EstimatedCost float64
}

// ConfigResult represents the result of a config fetch.
type ConfigResult struct {
	AgentID   string
	Config    map[string]interface{}
	Policies  []PolicyConfig
	UpdatedAt string
}

// SecretsResult represents the result of a secrets fetch.
type SecretsResult struct {
	Secrets   map[string]string
	ExpiresAt string
}

// HeartbeatResult represents the result of a heartbeat.
type HeartbeatResult struct {
	Acknowledged         bool
	ConfigChanged        bool
	NextHeartbeatSeconds int
}
