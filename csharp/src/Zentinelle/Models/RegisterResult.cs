using System.Text.Json.Serialization;

namespace Zentinelle.Models;

/// <summary>
/// Result of agent registration.
/// </summary>
public class RegisterResult
{
    /// <summary>
    /// The assigned session ID.
    /// </summary>
    [JsonPropertyName("session_id")]
    public string SessionId { get; set; } = string.Empty;

    /// <summary>
    /// The agent configuration.
    /// </summary>
    [JsonPropertyName("config")]
    public PolicyConfig? Config { get; set; }

    /// <summary>
    /// Whether registration was successful.
    /// </summary>
    [JsonPropertyName("success")]
    public bool Success { get; set; }

    /// <summary>
    /// Any warnings from registration.
    /// </summary>
    [JsonPropertyName("warnings")]
    public List<string>? Warnings { get; set; }
}

/// <summary>
/// Options for agent registration.
/// </summary>
public class RegisterOptions
{
    /// <summary>
    /// User ID for the session.
    /// </summary>
    public string? UserId { get; set; }

    /// <summary>
    /// Custom session ID (auto-generated if not provided).
    /// </summary>
    public string? SessionId { get; set; }

    /// <summary>
    /// Additional metadata for the session.
    /// </summary>
    public Dictionary<string, object>? Metadata { get; set; }
}
