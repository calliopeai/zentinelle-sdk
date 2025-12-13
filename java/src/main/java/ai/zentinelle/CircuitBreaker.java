package ai.zentinelle;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Circuit breaker for failing fast when service is down.
 */
class CircuitBreaker {

    private enum State { CLOSED, OPEN, HALF_OPEN }

    private final int failureThreshold;
    private final Duration recoveryTimeout;
    private final int halfOpenMaxCalls;

    private final AtomicReference<State> state = new AtomicReference<>(State.CLOSED);
    private final AtomicInteger failureCount = new AtomicInteger(0);
    private final AtomicInteger halfOpenCalls = new AtomicInteger(0);
    private volatile Instant lastFailureTime;

    CircuitBreaker(int failureThreshold, Duration recoveryTimeout) {
        this.failureThreshold = failureThreshold;
        this.recoveryTimeout = recoveryTimeout;
        this.halfOpenMaxCalls = 3;
    }

    boolean canExecute() {
        State current = state.get();

        if (current == State.CLOSED) {
            return true;
        }

        if (current == State.OPEN) {
            if (lastFailureTime != null &&
                Duration.between(lastFailureTime, Instant.now()).compareTo(recoveryTimeout) > 0) {
                if (state.compareAndSet(State.OPEN, State.HALF_OPEN)) {
                    halfOpenCalls.set(0);
                }
                return true;
            }
            return false;
        }

        // HALF_OPEN
        return true;
    }

    void recordSuccess() {
        State current = state.get();

        if (current == State.HALF_OPEN) {
            if (halfOpenCalls.incrementAndGet() >= halfOpenMaxCalls) {
                state.set(State.CLOSED);
                failureCount.set(0);
            }
        } else if (current == State.CLOSED) {
            failureCount.set(0);
        }
    }

    void recordFailure() {
        failureCount.incrementAndGet();
        lastFailureTime = Instant.now();

        State current = state.get();

        if (current == State.HALF_OPEN) {
            state.set(State.OPEN);
        } else if (failureCount.get() >= failureThreshold) {
            state.set(State.OPEN);
        }
    }
}
