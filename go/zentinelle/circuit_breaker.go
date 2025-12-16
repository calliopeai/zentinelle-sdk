package zentinelle

import (
	"sync"
	"time"
)

// CircuitState represents the state of the circuit breaker.
type CircuitState int

const (
	CircuitClosed CircuitState = iota
	CircuitOpen
	CircuitHalfOpen
)

// CircuitBreaker implements the circuit breaker pattern.
type CircuitBreaker struct {
	mu               sync.Mutex
	state            CircuitState
	failureCount     int
	failureThreshold int
	lastFailureTime  time.Time
	recoveryTimeout  time.Duration
	halfOpenCalls    int
	halfOpenMaxCalls int
}

// NewCircuitBreaker creates a new circuit breaker.
func NewCircuitBreaker(threshold int, recoveryTimeout time.Duration) *CircuitBreaker {
	return &CircuitBreaker{
		state:            CircuitClosed,
		failureThreshold: threshold,
		recoveryTimeout:  recoveryTimeout,
		halfOpenMaxCalls: 3,
	}
}

// CanExecute returns whether a call should be allowed.
func (cb *CircuitBreaker) CanExecute() bool {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	switch cb.state {
	case CircuitClosed:
		return true
	case CircuitOpen:
		if time.Since(cb.lastFailureTime) > cb.recoveryTimeout {
			cb.state = CircuitHalfOpen
			cb.halfOpenCalls = 0
			return true
		}
		return false
	case CircuitHalfOpen:
		// Allow limited calls in half-open state to test recovery
		if cb.halfOpenCalls >= cb.halfOpenMaxCalls {
			return false // Wait for pending calls to complete
		}
		cb.halfOpenCalls++
		return true
	}
	return false
}

// RecordSuccess records a successful call.
// In half-open state, once halfOpenMaxCalls successes are recorded,
// the circuit transitions back to closed.
func (cb *CircuitBreaker) RecordSuccess() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	switch cb.state {
	case CircuitHalfOpen:
		// Check if we've reached the threshold for recovery
		if cb.halfOpenCalls >= cb.halfOpenMaxCalls {
			cb.state = CircuitClosed
			cb.failureCount = 0
			cb.halfOpenCalls = 0
		}
	case CircuitClosed:
		cb.failureCount = 0
	}
}

// RecordFailure records a failed call.
func (cb *CircuitBreaker) RecordFailure() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	cb.failureCount++
	cb.lastFailureTime = time.Now()

	switch cb.state {
	case CircuitHalfOpen:
		cb.state = CircuitOpen
	case CircuitClosed:
		if cb.failureCount >= cb.failureThreshold {
			cb.state = CircuitOpen
		}
	}
}

// State returns the current state.
func (cb *CircuitBreaker) State() CircuitState {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	return cb.state
}
