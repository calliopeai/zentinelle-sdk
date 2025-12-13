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
    [JsonPropertyName("policies")]
    public List<PolicyEvaluation>? Policies { get; set; }

    /// <summary>
    /// Whether human approval is required.
    /// </summary>
    [JsonPropertyName("requires_approval")]
    public bool RequiresApproval { get; set; }

    /// <summary>
    /// Workflow ID for approval requests.
    /// </summary>
    [JsonPropertyName("approval_workflow_id")]
    public string? ApprovalWorkflowId { get; set; }

    /// <summary>
    /// Metadata from the evaluation.
    /// </summary>
    [JsonPropertyName("metadata")]
    public Dictionary<string, object>? Metadata { get; set; }

    /// <summary>
    /// Checks if any policy blocked the action.
    /// </summary>
    public bool IsBlocked => !Allowed && !RequiresApproval;

    /// <summary>
    /// Gets the policies that blocked the action.
    /// </summary>
    public IEnumerable<PolicyEvaluation> GetBlockingPolicies()
    {
        return Policies?.Where(p => !p.Passed) ?? Enumerable.Empty<PolicyEvaluation>();
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
    [JsonPropertyName("policy")]
    public string? Policy { get; set; }

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
    /// Reason for the policy decision.
    /// </summary>
    [JsonPropertyName("reason")]
    public string? Reason { get; set; }

    /// <summary>
    /// Severity level if policy failed.
    /// </summary>
    [JsonPropertyName("severity")]
    public string? Severity { get; set; }
}
