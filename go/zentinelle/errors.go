package zentinelle

import "fmt"

// Error is the base error type for Zentinelle.
type Error struct {
	Message string
}

func (e *Error) Error() string {
	return e.Message
}

// ConnectionError is returned when unable to connect to Zentinelle.
type ConnectionError struct {
	Message string
}

func (e *ConnectionError) Error() string {
	return fmt.Sprintf("connection error: %s", e.Message)
}

// AuthError is returned when authentication fails.
type AuthError struct {
	Message string
}

func (e *AuthError) Error() string {
	return fmt.Sprintf("auth error: %s", e.Message)
}

// RateLimitError is returned when rate limit is exceeded.
type RateLimitError struct {
	Message    string
	RetryAfter int
}

func (e *RateLimitError) Error() string {
	return fmt.Sprintf("rate limit error: %s (retry after %ds)", e.Message, e.RetryAfter)
}

// PolicyViolationError is returned when a policy blocks an action.
type PolicyViolationError struct {
	Message string
	Result  *EvaluateResult
}

func (e *PolicyViolationError) Error() string {
	return fmt.Sprintf("policy violation: %s", e.Message)
}
