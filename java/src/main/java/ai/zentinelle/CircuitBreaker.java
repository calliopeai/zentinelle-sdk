package ai.zentinelle;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Circuit breaker for failing fast when service is down.
 *
 * Uses a lock-based approach for correct half-open state semantics:
 * - Tracks successful calls in half-open state (not just allowed calls)
 * - Prevents race conditions between concurrent requests
 */
class CircuitBreaker {

    private enum State { CLOSED, OPEN, HALF_OPEN }

    private final int failureThreshold;
    private final Duration recoveryTimeout;
    private final int halfOpenMaxCalls;

    private State state = State.CLOSED;
    private int failureCount = 0;
    private int halfOpenSuccesses = 0;  // Track successful calls, not just allowed
    private final AtomicInteger halfOpenInFlight = new AtomicInteger(0);  // Currently executing calls
    private Instant lastFailureTime;
    private final Object lock = new Object();

    CircuitBreaker(int failureThreshold, Duration recoveryTimeout) {
        this.failureThreshold = failureThreshold;
        this.recoveryTimeout = recoveryTimeout;
        this.halfOpenMaxCalls = 3;
    }

    boolean canExecute() {
        synchronized (lock) {
            switch (state) {
                case CLOSED:
                    return true;

                case OPEN:
                    if (lastFailureTime != null &&
                        Duration.between(lastFailureTime, Instant.now()).compareTo(recoveryTimeout) > 0) {
                        // Transition to half-open
                        state = State.HALF_OPEN;
                        halfOpenSuccesses = 0;
                        halfOpenInFlight.set(0);
                        // Allow this call
                        halfOpenInFlight.incrementAndGet();
                        return true;
                    }
                    return false;

                case HALF_OPEN:
                    // Limit concurrent calls in half-open state
                    if (halfOpenInFlight.get() < halfOpenMaxCalls) {
                        halfOpenInFlight.incrementAndGet();
                        return true;
                    }
                    return false;

                default:
                    return false;
            }
        }
    }

    void recordSuccess() {
        synchronized (lock) {
            switch (state) {
                case HALF_OPEN:
                    halfOpenInFlight.decrementAndGet();
                    halfOpenSuccesses++;
                    // Close circuit after N successful calls
                    if (halfOpenSuccesses >= halfOpenMaxCalls) {
                        state = State.CLOSED;
                        failureCount = 0;
                        halfOpenSuccesses = 0;
                    }
                    break;

                case CLOSED:
                    // Reset failure count on success
                    failureCount = 0;
                    break;

                default:
                    break;
            }
        }
    }

    void recordFailure() {
        synchronized (lock) {
            failureCount++;
            lastFailureTime = Instant.now();

            switch (state) {
                case HALF_OPEN:
                    halfOpenInFlight.decrementAndGet();
                    // Any failure in half-open goes back to open
                    state = State.OPEN;
                    break;

                case CLOSED:
                    if (failureCount >= failureThreshold) {
                        state = State.OPEN;
                    }
                    break;

                default:
                    break;
            }
        }
    }
}
