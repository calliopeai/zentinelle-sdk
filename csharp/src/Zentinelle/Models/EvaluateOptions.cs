namespace Zentinelle.Models;

/// <summary>
/// Options for policy evaluation requests.
/// </summary>
public class EvaluateOptions
{
    /// <summary>
    /// User ID for the evaluation.
    /// </summary>
    public string? UserId { get; set; }

    /// <summary>
    /// Session ID for the evaluation.
    /// </summary>
    public string? SessionId { get; set; }

    /// <summary>
    /// Additional context for policy evaluation.
    /// </summary>
    public Dictionary<string, object>? Context { get; set; }
}
