namespace Zentinelle.Models;

/// <summary>
/// An event to track in Zentinelle.
/// </summary>
public class Event
{
    /// <summary>
    /// Event type, such as <c>tool_call</c> or <c>model_request</c>.
    /// </summary>
    public string Type { get; set; } = string.Empty;

    /// <summary>
    /// Event category used for routing and storage.
    /// </summary>
    public EventCategory Category { get; set; } = EventCategory.Telemetry;

    /// <summary>
    /// Event payload.
    /// </summary>
    public Dictionary<string, object> Payload { get; set; } = new();

    /// <summary>
    /// User ID associated with this event.
    /// </summary>
    public string? UserId { get; set; }

    /// <summary>
    /// Event timestamp (set automatically if not provided).
    /// </summary>
    public DateTime? Timestamp { get; set; }

    /// <summary>
    /// Converts the event to the canonical API payload.
    /// </summary>
    public Dictionary<string, object> ToApiPayload()
    {
        return new Dictionary<string, object>
        {
            ["type"] = Type,
            ["category"] = Category switch
            {
                EventCategory.Telemetry => "telemetry",
                EventCategory.Audit => "audit",
                EventCategory.Alert => "alert",
                EventCategory.Compliance => "compliance",
                _ => "telemetry"
            },
            ["payload"] = Payload,
            ["timestamp"] = (Timestamp ?? DateTime.UtcNow).ToUniversalTime(),
            ["user_id"] = UserId ?? string.Empty
        };
    }

    /// <summary>
    /// Creates a success event.
    /// </summary>
    public static Event Succeeded(EventCategory category, string eventType)
    {
        return new Event
        {
            Category = category,
            Type = eventType,
            Payload = new Dictionary<string, object>
            {
                ["success"] = true
            }
        };
    }

    /// <summary>
    /// Creates a failure event.
    /// </summary>
    public static Event Failed(EventCategory category, string eventType, string? error = null)
    {
        var payload = new Dictionary<string, object>
        {
            ["success"] = false
        };
        if (!string.IsNullOrWhiteSpace(error))
        {
            payload["error"] = error;
        }

        return new Event
        {
            Category = category,
            Type = eventType,
            Payload = payload
        };
    }

    /// <summary>
    /// Creates a tool call event.
    /// </summary>
    public static Event ToolCall(string toolName, bool success, Dictionary<string, object>? metadata = null)
    {
        var payload = new Dictionary<string, object>
        {
            ["tool"] = toolName,
            ["success"] = success
        };
        if (metadata != null)
        {
            payload["metadata"] = metadata;
        }

        return new Event
        {
            Category = EventCategory.Audit,
            Type = "tool_call",
            Payload = payload
        };
    }

    /// <summary>
    /// Creates a model request event.
    /// </summary>
    public static Event ModelRequest(string model, ModelUsage usage, bool success = true)
    {
        return new Event
        {
            Category = EventCategory.Telemetry,
            Type = "model_request",
            Payload = new Dictionary<string, object>
            {
                ["provider"] = usage.Provider ?? string.Empty,
                ["model"] = model,
                ["input_tokens"] = usage.InputTokens,
                ["output_tokens"] = usage.OutputTokens,
                ["estimated_cost"] = usage.EstimatedCost ?? 0m,
                ["success"] = success
            }
        };
    }
}

/// <summary>
/// Event category types.
/// </summary>
public enum EventCategory
{
    Telemetry,
    Audit,
    Alert,
    Compliance
}

/// <summary>
/// Model usage information.
/// </summary>
public class ModelUsage
{
    /// <summary>
    /// Provider identifier.
    /// </summary>
    public string? Provider { get; set; }

    /// <summary>
    /// Model identifier.
    /// </summary>
    public string? Model { get; set; }

    /// <summary>
    /// Number of input tokens.
    /// </summary>
    public int InputTokens { get; set; }

    /// <summary>
    /// Number of output tokens.
    /// </summary>
    public int OutputTokens { get; set; }

    /// <summary>
    /// Total tokens used.
    /// </summary>
    public int TotalTokens => InputTokens + OutputTokens;

    /// <summary>
    /// Estimated cost in dollars.
    /// </summary>
    public decimal? EstimatedCost { get; set; }

    /// <summary>
    /// Backwards-compatible alias for <see cref="EstimatedCost"/>.
    /// </summary>
    public decimal? Cost
    {
        get => EstimatedCost;
        set => EstimatedCost = value;
    }
}
