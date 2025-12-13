package ai.zentinelle.exception;

/**
 * Exception thrown when unable to connect to Zentinelle.
 */
public class ConnectionException extends ZentinelleException {

    public ConnectionException(String message) {
        super(message);
    }
}
