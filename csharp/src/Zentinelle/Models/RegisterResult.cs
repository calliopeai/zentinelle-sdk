using System.Text.Json.Serialization;

namespace Zentinelle.Models;

/// <summary>
/// Result of agent registration.
/// </summary>
public class RegisterResult
{
    /// <summary>
    /// The registered agent ID.
    /// </summary>
    [JsonPropertyName("agent_id")]
    public string AgentId { get; set; } = string.Empty;

    /// <summary>
    /// The runtime API key returned after bootstrap registration.
    /// </summary>
    [JsonPropertyName("api_key")]
    public string? ApiKey { get; set; }

    /// <summary>
    /// Runtime configuration for the agent.
    /// </summary>
    [JsonPropertyName("config")]
    public Dictionary<string, object> Config { get; set; } = new();

    /// <summary>
    /// Effective policies returned during registration.
    /// </summary>
    [JsonPropertyName("policies")]
    public List<PolicyConfig> Policies { get; set; } = new();
}

/// <summary>
/// Options for agent registration.
/// </summary>
public class RegisterOptions
{
    /// <summary>
    /// Declared agent capabilities.
    /// </summary>
    public List<string> Capabilities { get; set; } = new();

    /// <summary>
    /// Additional metadata for the agent.
    /// </summary>
    public Dictionary<string, object> Metadata { get; set; } = new();

    /// <summary>
    /// Optional display name for the agent.
    /// </summary>
    public string? Name { get; set; }
}
