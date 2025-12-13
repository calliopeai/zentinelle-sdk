package ai.zentinelle.exception;

/**
 * Exception thrown when authentication fails.
 */
public class AuthException extends ZentinelleException {

    public AuthException(String message) {
        super(message);
    }
}
