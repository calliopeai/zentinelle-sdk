namespace Zentinelle.Exceptions;

/// <summary>
/// Base exception for all Zentinelle errors.
/// </summary>
public class ZentinelleException : Exception
{
    /// <summary>
    /// Creates a new Zentinelle exception.
    /// </summary>
    public ZentinelleException(string message) : base(message) { }

    /// <summary>
    /// Creates a new Zentinelle exception with an inner exception.
    /// </summary>
    public ZentinelleException(string message, Exception innerException)
        : base(message, innerException) { }
}

/// <summary>
/// Exception thrown when authentication fails.
/// </summary>
public class AuthenticationException : ZentinelleException
{
    /// <summary>
    /// Creates a new authentication exception.
    /// </summary>
    public AuthenticationException(string message) : base(message) { }
}

/// <summary>
/// Exception thrown when a connection error occurs.
/// </summary>
public class ConnectionException : ZentinelleException
{
    /// <summary>
    /// Creates a new connection exception.
    /// </summary>
    public ConnectionException(string message) : base(message) { }

    /// <summary>
    /// Creates a new connection exception with an inner exception.
    /// </summary>
    public ConnectionException(string message, Exception innerException)
        : base(message, innerException) { }
}

/// <summary>
/// Exception thrown when rate limit is exceeded.
/// </summary>
public class RateLimitException : ZentinelleException
{
    /// <summary>
    /// Seconds to wait before retrying.
    /// </summary>
    public int RetryAfterSeconds { get; }

    /// <summary>
    /// Creates a new rate limit exception.
    /// </summary>
    public RateLimitException(string message, int retryAfterSeconds) : base(message)
    {
        RetryAfterSeconds = retryAfterSeconds;
    }
}

/// <summary>
/// Exception thrown when circuit breaker is open.
/// </summary>
public class CircuitBreakerOpenException : ZentinelleException
{
    /// <summary>
    /// Creates a new circuit breaker exception.
    /// </summary>
    public CircuitBreakerOpenException(string message) : base(message) { }
}

/// <summary>
/// Exception thrown when a policy blocks an action.
/// </summary>
public class PolicyViolationException : ZentinelleException
{
    /// <summary>
    /// The evaluation result that caused this exception.
    /// </summary>
    public Models.EvaluateResult Result { get; }

    /// <summary>
    /// Creates a new policy violation exception.
    /// </summary>
    public PolicyViolationException(string message, Models.EvaluateResult result)
        : base(message)
    {
        Result = result;
    }
}
