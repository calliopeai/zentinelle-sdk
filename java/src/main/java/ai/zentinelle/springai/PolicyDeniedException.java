package ai.zentinelle.springai;

import ai.zentinelle.model.EvaluateResult;

/**
 * A Spring AI request was refused by Zentinelle policy.
 *
 * <p>Unchecked, and that is forced rather than chosen. Spring AI's
 * {@code CallAdvisor.adviseCall} declares no checked exceptions, so the SDK's
 * own {@link ai.zentinelle.exception.PolicyViolationException} — which extends
 * the checked {@code ZentinelleException} — cannot be thrown from an advisor.
 * The alternatives were to make the SDK's exception hierarchy unchecked, which
 * would change the API every existing caller compiles against, or to return a
 * response pretending the model had answered, which would hide the denial.
 *
 * <p>{@link #getResult()} is null when the refusal came from the control plane
 * being unreachable rather than from a policy: on that path no evaluation ever
 * returned, and inventing a denied result would make a availability failure
 * indistinguishable from a policy decision in the audit trail.
 */
public class PolicyDeniedException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    private final transient EvaluateResult result;

    public PolicyDeniedException(String message, EvaluateResult result) {
        super(message);
        this.result = result;
    }

    /**
     * The evaluation that refused this call, or null if the check itself failed.
     */
    public EvaluateResult getResult() {
        return this.result;
    }
}
