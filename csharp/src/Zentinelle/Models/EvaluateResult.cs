using System.Text.Json.Serialization;

namespace Zentinelle.Models;

/// <summary>
/// Result of a policy evaluation.
/// </summary>
public class EvaluateResult
{
    /// <summary>
    /// Whether the action is allowed.
    /// </summary>
    [JsonPropertyName("allowed")]
    public bool Allowed { get; set; }

    /// <summary>
    /// Reason for the decision.
    /// </summary>
    [JsonPropertyName("reason")]
    public string? Reason { get; set; }

    /// <summary>
    /// Whether the decision was made due to fail-open mode.
    /// </summary>
    [JsonPropertyName("fail_open")]
    public bool FailOpen { get; set; }

    /// <summary>
    /// Individual policy evaluations.
    /// </summary>
    [JsonPropertyName("policies_evaluated")]
    public List<PolicyEvaluation> PoliciesEvaluated { get; set; } = new();

    /// <summary>
    /// Warnings returned by the service.
    /// </summary>
    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = new();

    /// <summary>
    /// Additional evaluation context.
    /// </summary>
    [JsonPropertyName("context")]
    public Dictionary<string, object> Context { get; set; } = new();

    /// <summary>
    /// Checks if any policy blocked the action.
    /// </summary>
    public bool IsBlocked => !Allowed;

    /// <summary>
    /// Whether human approval is required.
    /// </summary>
    public bool RequiresHumanApproval =>
        Context.TryGetValue("require_human_approval", out var value) &&
        value is bool required &&
        required;

    /// <summary>
    /// Gets the policies that blocked the action.
    /// </summary>
    public IEnumerable<PolicyEvaluation> GetBlockingPolicies()
    {
        return PoliciesEvaluated.Where(p => !p.Passed);
    }
}

/// <summary>
/// Result of an individual policy evaluation.
/// </summary>
public class PolicyEvaluation
{
    /// <summary>
    /// Name of the policy.
    /// </summary>
    [JsonPropertyName("name")]
    public string? Name { get; set; }

    /// <summary>
    /// Type of the policy.
    /// </summary>
    [JsonPropertyName("type")]
    public string? Type { get; set; }

    /// <summary>
    /// Whether the policy passed.
    /// </summary>
    [JsonPropertyName("passed")]
    public bool Passed { get; set; }

    /// <summary>
    /// Human-readable message for the policy result.
    /// </summary>
    [JsonPropertyName("message")]
    public string? Message { get; set; }
}
