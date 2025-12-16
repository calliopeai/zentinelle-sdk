package ai.zentinelle.exception;

/**
 * Exception thrown when rate limit is exceeded.
 */
public class RateLimitException extends ZentinelleException {

    private final int retryAfter;

    public RateLimitException(String message, int retryAfter) {
        super(message);
        this.retryAfter = retryAfter;
    }

    /**
     * Returns the number of seconds to wait before retrying.
     */
    public int getRetryAfter() {
        return retryAfter;
    }
}
