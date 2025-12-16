package ai.zentinelle.model;

import java.util.List;
import java.util.Map;

/**
 * Result of a policy evaluation.
 */
public class EvaluateResult {

    private final boolean allowed;
    private final String reason;
    private final List<PolicyEvaluation> policiesEvaluated;
    private final List<String> warnings;
    private final Map<String, Object> context;
    private final boolean failOpen;

    private EvaluateResult(Builder builder) {
        this.allowed = builder.allowed;
        this.reason = builder.reason;
        this.policiesEvaluated = builder.policiesEvaluated != null ? builder.policiesEvaluated : List.of();
        this.warnings = builder.warnings != null ? builder.warnings : List.of();
        this.context = builder.context != null ? builder.context : Map.of();
        this.failOpen = builder.failOpen;
    }

    public boolean isAllowed() { return allowed; }
    public String getReason() { return reason; }
    public List<PolicyEvaluation> getPoliciesEvaluated() { return policiesEvaluated; }
    public List<String> getWarnings() { return warnings; }
    public Map<String, Object> getContext() { return context; }

    /**
     * Returns true if this result was returned due to fail-open mode (service unavailable).
     */
    public boolean isFailOpen() { return failOpen; }

    /**
     * Returns true if human approval is required.
     */
    public boolean requiresHumanApproval() {
        Object required = context.get("require_human_approval");
        return Boolean.TRUE.equals(required);
    }

    /**
     * Returns the list of policies that blocked this action.
     */
    public List<String> getBlockedPolicies() {
        return policiesEvaluated.stream()
            .filter(p -> !p.isPassed())
            .map(PolicyEvaluation::getName)
            .toList();
    }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private boolean allowed;
        private String reason;
        private List<PolicyEvaluation> policiesEvaluated;
        private List<String> warnings;
        private Map<String, Object> context;
        private boolean failOpen;

        public Builder allowed(boolean allowed) { this.allowed = allowed; return this; }
        public Builder reason(String reason) { this.reason = reason; return this; }
        public Builder policiesEvaluated(List<PolicyEvaluation> policies) { this.policiesEvaluated = policies; return this; }
        public Builder warnings(List<String> warnings) { this.warnings = warnings; return this; }
        public Builder context(Map<String, Object> context) { this.context = context; return this; }
        public Builder failOpen(boolean failOpen) { this.failOpen = failOpen; return this; }

        public EvaluateResult build() { return new EvaluateResult(this); }
    }
}
