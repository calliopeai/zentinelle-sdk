using System.Text.Json.Serialization;

namespace Zentinelle.Models;

/// <summary>
/// Result of a config fetch.
/// </summary>
public class ConfigResult
{
    /// <summary>
    /// Agent identifier.
    /// </summary>
    [JsonPropertyName("agent_id")]
    public string AgentId { get; set; } = string.Empty;

    /// <summary>
    /// Runtime config payload.
    /// </summary>
    [JsonPropertyName("config")]
    public Dictionary<string, object> Config { get; set; } = new();

    /// <summary>
    /// Effective policies for the agent.
    /// </summary>
    [JsonPropertyName("policies")]
    public List<PolicyConfig> Policies { get; set; } = new();

    /// <summary>
    /// Timestamp for the last config update.
    /// </summary>
    [JsonPropertyName("updated_at")]
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}
