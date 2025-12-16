package ai.zentinelle.exception;

import ai.zentinelle.model.EvaluateResult;

/**
 * Exception thrown when a policy blocks an action.
 */
public class PolicyViolationException extends ZentinelleException {

    private final EvaluateResult result;

    public PolicyViolationException(String message, EvaluateResult result) {
        super(message);
        this.result = result;
    }

    /**
     * Returns the evaluation result that caused this exception.
     */
    public EvaluateResult getResult() {
        return result;
    }
}
