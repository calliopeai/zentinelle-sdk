using System.Text.Json.Serialization;

namespace Zentinelle.Models;

/// <summary>
/// An event to track in Zentinelle.
/// </summary>
public class Event
{
    /// <summary>
    /// Event category.
    /// </summary>
    [JsonPropertyName("category")]
    public EventCategory Category { get; set; }

    /// <summary>
    /// Action that was performed.
    /// </summary>
    [JsonPropertyName("action")]
    public string Action { get; set; } = string.Empty;

    /// <summary>
    /// Whether the action succeeded.
    /// </summary>
    [JsonPropertyName("success")]
    public bool Success { get; set; }

    /// <summary>
    /// Agent ID (set automatically if not provided).
    /// </summary>
    [JsonPropertyName("agent_id")]
    public string? AgentId { get; set; }

    /// <summary>
    /// User ID associated with this event.
    /// </summary>
    [JsonPropertyName("user_id")]
    public string? UserId { get; set; }

    /// <summary>
    /// Session ID associated with this event.
    /// </summary>
    [JsonPropertyName("session_id")]
    public string? SessionId { get; set; }

    /// <summary>
    /// Event timestamp (set automatically if not provided).
    /// </summary>
    [JsonPropertyName("timestamp")]
    public DateTime? Timestamp { get; set; }

    /// <summary>
    /// Duration of the action in milliseconds.
    /// </summary>
    [JsonPropertyName("duration_ms")]
    public long? DurationMs { get; set; }

    /// <summary>
    /// Model usage information.
    /// </summary>
    [JsonPropertyName("model_usage")]
    public ModelUsage? ModelUsage { get; set; }

    /// <summary>
    /// Additional metadata.
    /// </summary>
    [JsonPropertyName("metadata")]
    public Dictionary<string, object>? Metadata { get; set; }

    /// <summary>
    /// Creates a success event.
    /// </summary>
    public static Event Succeeded(EventCategory category, string action)
    {
        return new Event
        {
            Category = category,
            Action = action,
            Success = true
        };
    }

    /// <summary>
    /// Creates a failure event.
    /// </summary>
    public static Event Failed(EventCategory category, string action, string? error = null)
    {
        return new Event
        {
            Category = category,
            Action = action,
            Success = false,
            Metadata = error != null ? new Dictionary<string, object> { ["error"] = error } : null
        };
    }

    /// <summary>
    /// Creates a tool call event.
    /// </summary>
    public static Event ToolCall(string toolName, bool success, Dictionary<string, object>? metadata = null)
    {
        return new Event
        {
            Category = EventCategory.ToolCall,
            Action = toolName,
            Success = success,
            Metadata = metadata
        };
    }

    /// <summary>
    /// Creates a model request event.
    /// </summary>
    public static Event ModelRequest(string model, ModelUsage usage, bool success = true)
    {
        return new Event
        {
            Category = EventCategory.ModelRequest,
            Action = model,
            Success = success,
            ModelUsage = usage
        };
    }
}

/// <summary>
/// Event category types.
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum EventCategory
{
    /// <summary>Model/LLM request.</summary>
    [JsonPropertyName("model_request")]
    ModelRequest,

    /// <summary>Tool/function call.</summary>
    [JsonPropertyName("tool_call")]
    ToolCall,

    /// <summary>Policy evaluation.</summary>
    [JsonPropertyName("policy_evaluation")]
    PolicyEvaluation,

    /// <summary>User interaction.</summary>
    [JsonPropertyName("user_interaction")]
    UserInteraction,

    /// <summary>Error occurred.</summary>
    [JsonPropertyName("error")]
    Error,

    /// <summary>Custom event.</summary>
    [JsonPropertyName("custom")]
    Custom
}

/// <summary>
/// Model usage information.
/// </summary>
public class ModelUsage
{
    /// <summary>
    /// Model identifier.
    /// </summary>
    [JsonPropertyName("model")]
    public string? Model { get; set; }

    /// <summary>
    /// Number of input tokens.
    /// </summary>
    [JsonPropertyName("input_tokens")]
    public int InputTokens { get; set; }

    /// <summary>
    /// Number of output tokens.
    /// </summary>
    [JsonPropertyName("output_tokens")]
    public int OutputTokens { get; set; }

    /// <summary>
    /// Total tokens used.
    /// </summary>
    [JsonPropertyName("total_tokens")]
    public int TotalTokens => InputTokens + OutputTokens;

    /// <summary>
    /// Estimated cost in dollars.
    /// </summary>
    [JsonPropertyName("cost")]
    public decimal? Cost { get; set; }
}
