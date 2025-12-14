namespace Zentinelle;

/// <summary>
/// Configuration options for the Zentinelle client.
/// </summary>
public class ZentinelleOptions
{
    /// <summary>
    /// Your Zentinelle API key. Required.
    /// </summary>
    public required string ApiKey { get; set; }

    /// <summary>
    /// The agent ID to use for requests. Required.
    /// </summary>
    public required string AgentId { get; set; }

    /// <summary>
    /// The type of agent (e.g., "langchain", "crewai", "custom"). Required.
    /// </summary>
    public required string AgentType { get; set; }

    /// <summary>
    /// Base URL for the Zentinelle API.
    /// </summary>
    public string BaseUrl { get; set; } = "https://api.zentinelle.ai";

    /// <summary>
    /// HTTP request timeout.
    /// </summary>
    public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(30);

    /// <summary>
    /// Maximum number of retry attempts for failed requests.
    /// </summary>
    public int MaxRetries { get; set; } = 3;

    /// <summary>
    /// Whether to allow actions when Zentinelle is unreachable.
    /// </summary>
    public bool FailOpen { get; set; } = true;

    /// <summary>
    /// Number of failures before the circuit breaker opens.
    /// </summary>
    public int CircuitBreakerThreshold { get; set; } = 5;

    /// <summary>
    /// Time to wait before attempting recovery after circuit breaker opens.
    /// </summary>
    public TimeSpan CircuitBreakerRecovery { get; set; } = TimeSpan.FromSeconds(30);

    /// <summary>
    /// Interval between heartbeat requests.
    /// </summary>
    public TimeSpan HeartbeatInterval { get; set; } = TimeSpan.FromSeconds(30);

    /// <summary>
    /// Interval between event buffer flushes.
    /// </summary>
    public TimeSpan FlushInterval { get; set; } = TimeSpan.FromSeconds(5);

    /// <summary>
    /// Maximum number of events to batch in a single flush.
    /// </summary>
    public int MaxBatchSize { get; set; } = 100;

    /// <summary>
    /// How long to cache configuration responses.
    /// </summary>
    public TimeSpan ConfigCacheDuration { get; set; } = TimeSpan.FromMinutes(5);
}
