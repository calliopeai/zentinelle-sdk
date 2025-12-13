package ai.zentinelle.exception;

/**
 * Base exception for Zentinelle SDK errors.
 */
public class ZentinelleException extends Exception {

    public ZentinelleException(String message) {
        super(message);
    }

    public ZentinelleException(String message, Throwable cause) {
        super(message, cause);
    }
}
