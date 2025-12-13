namespace Zentinelle.Resilience;

/// <summary>
/// Circuit breaker for failing fast when the service is unavailable.
/// </summary>
internal class CircuitBreaker
{
    private readonly int _failureThreshold;
    private readonly TimeSpan _recoveryTimeout;
    private readonly int _halfOpenMaxCalls;
    private readonly object _lock = new();

    private CircuitState _state = CircuitState.Closed;
    private int _failureCount;
    private int _halfOpenCalls;
    private DateTime? _lastFailureTime;

    /// <summary>
    /// Current state of the circuit breaker.
    /// </summary>
    public CircuitState State
    {
        get
        {
            lock (_lock)
            {
                return _state;
            }
        }
    }

    /// <summary>
    /// Creates a new circuit breaker.
    /// </summary>
    public CircuitBreaker(int failureThreshold, TimeSpan recoveryTimeout, int halfOpenMaxCalls = 3)
    {
        _failureThreshold = failureThreshold;
        _recoveryTimeout = recoveryTimeout;
        _halfOpenMaxCalls = halfOpenMaxCalls;
    }

    /// <summary>
    /// Checks if an operation can be executed.
    /// </summary>
    public bool CanExecute()
    {
        lock (_lock)
        {
            switch (_state)
            {
                case CircuitState.Closed:
                    return true;

                case CircuitState.Open:
                    if (_lastFailureTime.HasValue &&
                        DateTime.UtcNow - _lastFailureTime.Value > _recoveryTimeout)
                    {
                        _state = CircuitState.HalfOpen;
                        _halfOpenCalls = 0;
                        return true;
                    }
                    return false;

                case CircuitState.HalfOpen:
                    return true;

                default:
                    return false;
            }
        }
    }

    /// <summary>
    /// Records a successful operation.
    /// </summary>
    public void RecordSuccess()
    {
        lock (_lock)
        {
            switch (_state)
            {
                case CircuitState.HalfOpen:
                    _halfOpenCalls++;
                    if (_halfOpenCalls >= _halfOpenMaxCalls)
                    {
                        _state = CircuitState.Closed;
                        _failureCount = 0;
                    }
                    break;

                case CircuitState.Closed:
                    _failureCount = 0;
                    break;
            }
        }
    }

    /// <summary>
    /// Records a failed operation.
    /// </summary>
    public void RecordFailure()
    {
        lock (_lock)
        {
            _failureCount++;
            _lastFailureTime = DateTime.UtcNow;

            if (_state == CircuitState.HalfOpen)
            {
                _state = CircuitState.Open;
            }
            else if (_failureCount >= _failureThreshold)
            {
                _state = CircuitState.Open;
            }
        }
    }

    /// <summary>
    /// Resets the circuit breaker to closed state.
    /// </summary>
    public void Reset()
    {
        lock (_lock)
        {
            _state = CircuitState.Closed;
            _failureCount = 0;
            _halfOpenCalls = 0;
            _lastFailureTime = null;
        }
    }
}

/// <summary>
/// Circuit breaker states.
/// </summary>
public enum CircuitState
{
    /// <summary>Circuit is closed, operations allowed.</summary>
    Closed,

    /// <summary>Circuit is open, operations blocked.</summary>
    Open,

    /// <summary>Circuit is testing if service recovered.</summary>
    HalfOpen
}
