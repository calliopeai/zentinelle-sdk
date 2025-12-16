using System.Text.Json.Serialization;

namespace Zentinelle.Models;

/// <summary>
/// Agent policy configuration from Zentinelle.
/// </summary>
public class PolicyConfig
{
    /// <summary>
    /// The agent ID.
    /// </summary>
    [JsonPropertyName("agent_id")]
    public string? AgentId { get; set; }

    /// <summary>
    /// Active policies for this agent.
    /// </summary>
    [JsonPropertyName("policies")]
    public List<PolicyDefinition>? Policies { get; set; }

    /// <summary>
    /// Rate limit settings.
    /// </summary>
    [JsonPropertyName("rate_limits")]
    public RateLimits? RateLimits { get; set; }

    /// <summary>
    /// List of allowed model identifiers.
    /// </summary>
    [JsonPropertyName("allowed_models")]
    public List<string>? AllowedModels { get; set; }

    /// <summary>
    /// List of allowed tool names.
    /// </summary>
    [JsonPropertyName("allowed_tools")]
    public List<string>? AllowedTools { get; set; }

    /// <summary>
    /// Custom configuration values.
    /// </summary>
    [JsonPropertyName("custom")]
    public Dictionary<string, object>? Custom { get; set; }

    /// <summary>
    /// Whether a specific model is allowed.
    /// </summary>
    public bool IsModelAllowed(string model)
    {
        if (AllowedModels == null || AllowedModels.Count == 0)
            return true;
        return AllowedModels.Contains(model, StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>
    /// Whether a specific tool is allowed.
    /// </summary>
    public bool IsToolAllowed(string tool)
    {
        if (AllowedTools == null || AllowedTools.Count == 0)
            return true;
        return AllowedTools.Contains(tool, StringComparer.OrdinalIgnoreCase);
    }
}

/// <summary>
/// Definition of a policy.
/// </summary>
public class PolicyDefinition
{
    /// <summary>
    /// Policy identifier.
    /// </summary>
    [JsonPropertyName("id")]
    public string? Id { get; set; }

    /// <summary>
    /// Policy name.
    /// </summary>
    [JsonPropertyName("name")]
    public string? Name { get; set; }

    /// <summary>
    /// Policy type.
    /// </summary>
    [JsonPropertyName("type")]
    public string? Type { get; set; }

    /// <summary>
    /// Whether the policy is enabled.
    /// </summary>
    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    /// <summary>
    /// Policy configuration.
    /// </summary>
    [JsonPropertyName("config")]
    public Dictionary<string, object>? Config { get; set; }
}

/// <summary>
/// Rate limit configuration.
/// </summary>
public class RateLimits
{
    /// <summary>
    /// Maximum requests per minute.
    /// </summary>
    [JsonPropertyName("requests_per_minute")]
    public int RequestsPerMinute { get; set; }

    /// <summary>
    /// Maximum tokens per minute.
    /// </summary>
    [JsonPropertyName("tokens_per_minute")]
    public int TokensPerMinute { get; set; }

    /// <summary>
    /// Maximum tokens per day.
    /// </summary>
    [JsonPropertyName("tokens_per_day")]
    public int TokensPerDay { get; set; }

    /// <summary>
    /// Maximum cost per day in dollars.
    /// </summary>
    [JsonPropertyName("cost_per_day")]
    public decimal CostPerDay { get; set; }
}
