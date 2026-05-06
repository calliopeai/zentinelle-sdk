using System.Text.Json.Serialization;

namespace Zentinelle.Models;

/// <summary>
/// Effective policy configuration for an agent.
/// </summary>
public class PolicyConfig
{
    /// <summary>
    /// Policy identifier.
    /// </summary>
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>
    /// Policy name.
    /// </summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// Policy type.
    /// </summary>
    [JsonPropertyName("type")]
    public string Type { get; set; } = string.Empty;

    /// <summary>
    /// Enforcement mode for the policy.
    /// </summary>
    [JsonPropertyName("enforcement")]
    public string Enforcement { get; set; } = string.Empty;

    /// <summary>
    /// Policy-specific configuration payload.
    /// </summary>
    [JsonPropertyName("config")]
    public Dictionary<string, object> Config { get; set; } = new();

    /// <summary>
    /// Policy priority where lower numbers are evaluated first.
    /// </summary>
    [JsonPropertyName("priority")]
    public int? Priority { get; set; }

    /// <summary>
    /// Returns true when the policy is actively enforced.
    /// </summary>
    public bool IsEnforced => string.Equals(Enforcement, "enforce", StringComparison.OrdinalIgnoreCase);
}
