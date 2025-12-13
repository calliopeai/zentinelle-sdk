using System.Collections.Concurrent;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Zentinelle.Exceptions;
using Zentinelle.Models;
using Zentinelle.Resilience;

namespace Zentinelle;

/// <summary>
/// Client for interacting with the Zentinelle AI governance platform.
/// Thread-safe and designed for reuse across your application.
/// </summary>
public sealed class ZentinelleClient : IDisposable, IAsyncDisposable
{
    private readonly HttpClient _httpClient;
    private readonly ZentinelleOptions _options;
    private readonly ILogger<ZentinelleClient> _logger;
    private readonly CircuitBreaker _circuitBreaker;
    private readonly ConcurrentQueue<Event> _eventBuffer;
    private readonly Timer _flushTimer;
    private readonly Timer _heartbeatTimer;
    private readonly SemaphoreSlim _flushLock = new(1, 1);
    private readonly CancellationTokenSource _cts = new();

    private PolicyConfig? _cachedConfig;
    private DateTime _configCacheTime;
    private bool _disposed;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = false
    };

    /// <summary>
    /// Creates a new Zentinelle client with the specified options.
    /// </summary>
    /// <param name="options">Client configuration options.</param>
    /// <param name="logger">Optional logger instance.</param>
    /// <param name="httpClient">Optional custom HttpClient instance.</param>
    public ZentinelleClient(
        ZentinelleOptions options,
        ILogger<ZentinelleClient>? logger = null,
        HttpClient? httpClient = null)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));
        _logger = logger ?? NullLogger<ZentinelleClient>.Instance;

        _httpClient = httpClient ?? new HttpClient();
        _httpClient.BaseAddress = new Uri(options.BaseUrl);
        _httpClient.DefaultRequestHeaders.Add("X-Sentinel-Key", options.ApiKey);
        _httpClient.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        _httpClient.Timeout = options.Timeout;

        _circuitBreaker = new CircuitBreaker(
            options.CircuitBreakerThreshold,
            options.CircuitBreakerRecovery);

        _eventBuffer = new ConcurrentQueue<Event>();

        _flushTimer = new Timer(
            _ => _ = FlushEventsAsync(),
            null,
            options.FlushInterval,
            options.FlushInterval);

        _heartbeatTimer = new Timer(
            _ => _ = SendHeartbeatAsync(),
            null,
            options.HeartbeatInterval,
            options.HeartbeatInterval);
    }

    /// <summary>
    /// Creates a new Zentinelle client using environment variables.
    /// </summary>
    public static ZentinelleClient FromEnvironment(ILogger<ZentinelleClient>? logger = null)
    {
        var apiKey = Environment.GetEnvironmentVariable("ZENTINELLE_API_KEY")
            ?? throw new InvalidOperationException("ZENTINELLE_API_KEY environment variable not set");
        var agentId = Environment.GetEnvironmentVariable("ZENTINELLE_AGENT_ID")
            ?? throw new InvalidOperationException("ZENTINELLE_AGENT_ID environment variable not set");

        return new ZentinelleClient(new ZentinelleOptions
        {
            ApiKey = apiKey,
            AgentId = agentId
        }, logger);
    }

    /// <summary>
    /// Registers the agent session with Zentinelle.
    /// </summary>
    public async Task<RegisterResult> RegisterAsync(
        RegisterOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        var request = new
        {
            agent_id = _options.AgentId,
            user_id = options?.UserId,
            session_id = options?.SessionId ?? Guid.NewGuid().ToString(),
            metadata = options?.Metadata
        };

        var response = await SendRequestAsync<RegisterResult>(
            HttpMethod.Post,
            "/app/api/sentinel/v1/register",
            request,
            cancellationToken);

        _cachedConfig = response.Config;
        _configCacheTime = DateTime.UtcNow;

        _logger.LogInformation("Agent registered with session {SessionId}", response.SessionId);
        return response;
    }

    /// <summary>
    /// Evaluates an action against configured policies.
    /// </summary>
    public async Task<EvaluateResult> EvaluateAsync(
        string action,
        EvaluateOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrEmpty(action))
            throw new ArgumentException("Action cannot be null or empty", nameof(action));

        var request = new
        {
            agent_id = _options.AgentId,
            action,
            user_id = options?.UserId,
            context = options?.Context
        };

        return await SendRequestAsync<EvaluateResult>(
            HttpMethod.Post,
            "/app/api/sentinel/v1/evaluate",
            request,
            cancellationToken);
    }

    /// <summary>
    /// Evaluates an action synchronously.
    /// </summary>
    public EvaluateResult Evaluate(string action, EvaluateOptions? options = null)
    {
        return EvaluateAsync(action, options).GetAwaiter().GetResult();
    }

    /// <summary>
    /// Emits an event for tracking.
    /// </summary>
    public void Emit(Event evt)
    {
        if (evt == null)
            throw new ArgumentNullException(nameof(evt));

        evt.Timestamp ??= DateTime.UtcNow;
        evt.AgentId ??= _options.AgentId;

        _eventBuffer.Enqueue(evt);

        if (_eventBuffer.Count >= _options.MaxBatchSize)
        {
            _ = FlushEventsAsync();
        }
    }

    /// <summary>
    /// Emits an event asynchronously and waits for confirmation.
    /// </summary>
    public async Task EmitAsync(Event evt, CancellationToken cancellationToken = default)
    {
        Emit(evt);
        await FlushEventsAsync(cancellationToken);
    }

    /// <summary>
    /// Gets the agent configuration from Zentinelle.
    /// </summary>
    public async Task<PolicyConfig> GetConfigAsync(
        bool forceRefresh = false,
        CancellationToken cancellationToken = default)
    {
        if (!forceRefresh &&
            _cachedConfig != null &&
            DateTime.UtcNow - _configCacheTime < _options.ConfigCacheDuration)
        {
            return _cachedConfig;
        }

        var response = await SendRequestAsync<PolicyConfig>(
            HttpMethod.Get,
            $"/app/api/sentinel/v1/config/{_options.AgentId}",
            null,
            cancellationToken);

        _cachedConfig = response;
        _configCacheTime = DateTime.UtcNow;
        return response;
    }

    /// <summary>
    /// Gets secrets configured for this agent.
    /// </summary>
    public async Task<Dictionary<string, string>> GetSecretsAsync(
        CancellationToken cancellationToken = default)
    {
        return await SendRequestAsync<Dictionary<string, string>>(
            HttpMethod.Get,
            $"/app/api/sentinel/v1/secrets/{_options.AgentId}",
            null,
            cancellationToken);
    }

    /// <summary>
    /// Flushes any buffered events immediately.
    /// </summary>
    public async Task FlushAsync(CancellationToken cancellationToken = default)
    {
        await FlushEventsAsync(cancellationToken);
    }

    private async Task FlushEventsAsync(CancellationToken cancellationToken = default)
    {
        if (_eventBuffer.IsEmpty) return;

        if (!await _flushLock.WaitAsync(0, cancellationToken))
            return; // Another flush is in progress

        try
        {
            var events = new List<Event>();
            while (events.Count < _options.MaxBatchSize && _eventBuffer.TryDequeue(out var evt))
            {
                events.Add(evt);
            }

            if (events.Count == 0) return;

            var request = new { events };
            await SendRequestAsync<object>(
                HttpMethod.Post,
                "/app/api/sentinel/v1/events",
                request,
                cancellationToken);

            _logger.LogDebug("Flushed {Count} events", events.Count);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to flush events");
        }
        finally
        {
            _flushLock.Release();
        }
    }

    private async Task SendHeartbeatAsync()
    {
        try
        {
            var request = new
            {
                agent_id = _options.AgentId,
                status = "healthy",
                metrics = new
                {
                    pending_events = _eventBuffer.Count,
                    circuit_breaker_state = _circuitBreaker.State.ToString()
                }
            };

            await SendRequestAsync<object>(
                HttpMethod.Post,
                "/app/api/sentinel/v1/heartbeat",
                request,
                _cts.Token);
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Heartbeat failed");
        }
    }

    private async Task<T> SendRequestAsync<T>(
        HttpMethod method,
        string path,
        object? body,
        CancellationToken cancellationToken)
    {
        if (!_circuitBreaker.CanExecute())
        {
            if (_options.FailOpen)
            {
                _logger.LogWarning("Circuit breaker open, failing open");
                return CreateFailOpenResponse<T>();
            }
            throw new CircuitBreakerOpenException("Circuit breaker is open");
        }

        var retries = 0;
        Exception? lastException = null;

        while (retries <= _options.MaxRetries)
        {
            try
            {
                using var request = new HttpRequestMessage(method, path);

                if (body != null)
                {
                    var json = JsonSerializer.Serialize(body, JsonOptions);
                    request.Content = new StringContent(json, Encoding.UTF8, "application/json");
                }

                using var response = await _httpClient.SendAsync(request, cancellationToken);

                if (response.IsSuccessStatusCode)
                {
                    _circuitBreaker.RecordSuccess();
                    var content = await response.Content.ReadAsStringAsync(cancellationToken);
                    return JsonSerializer.Deserialize<T>(content, JsonOptions)!;
                }

                // Handle specific error codes
                var statusCode = (int)response.StatusCode;
                var errorContent = await response.Content.ReadAsStringAsync(cancellationToken);

                if (statusCode == 401)
                    throw new AuthenticationException("Invalid API key");

                if (statusCode == 429)
                {
                    var retryAfter = response.Headers.RetryAfter?.Delta?.Seconds ?? 60;
                    throw new RateLimitException($"Rate limit exceeded", (int)retryAfter);
                }

                if (statusCode >= 500 && retries < _options.MaxRetries)
                {
                    lastException = new ZentinelleException($"Server error: {statusCode}");
                    retries++;
                    await Task.Delay(GetBackoffDelay(retries), cancellationToken);
                    continue;
                }

                throw new ZentinelleException($"Request failed: {statusCode} - {errorContent}");
            }
            catch (HttpRequestException ex)
            {
                _circuitBreaker.RecordFailure();
                lastException = new ConnectionException("Failed to connect to Zentinelle", ex);

                if (retries < _options.MaxRetries)
                {
                    retries++;
                    await Task.Delay(GetBackoffDelay(retries), cancellationToken);
                    continue;
                }

                if (_options.FailOpen)
                {
                    _logger.LogWarning(ex, "Request failed, failing open");
                    return CreateFailOpenResponse<T>();
                }
                throw lastException;
            }
            catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                _circuitBreaker.RecordFailure();
                lastException = new ConnectionException("Request timed out");

                if (retries < _options.MaxRetries)
                {
                    retries++;
                    await Task.Delay(GetBackoffDelay(retries), cancellationToken);
                    continue;
                }

                if (_options.FailOpen)
                {
                    _logger.LogWarning("Request timed out, failing open");
                    return CreateFailOpenResponse<T>();
                }
                throw lastException;
            }
        }

        throw lastException ?? new ZentinelleException("Request failed after retries");
    }

    private static TimeSpan GetBackoffDelay(int attempt)
    {
        var delayMs = Math.Min(1000 * Math.Pow(2, attempt - 1), 30000);
        var jitter = Random.Shared.NextDouble() * 0.2 * delayMs;
        return TimeSpan.FromMilliseconds(delayMs + jitter);
    }

    private static T CreateFailOpenResponse<T>()
    {
        if (typeof(T) == typeof(EvaluateResult))
        {
            return (T)(object)new EvaluateResult
            {
                Allowed = true,
                Reason = "fail_open",
                FailOpen = true
            };
        }
        return default!;
    }

    /// <inheritdoc />
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;

        _cts.Cancel();
        _flushTimer.Dispose();
        _heartbeatTimer.Dispose();

        // Synchronous flush
        FlushEventsAsync().GetAwaiter().GetResult();

        _httpClient.Dispose();
        _flushLock.Dispose();
        _cts.Dispose();
    }

    /// <inheritdoc />
    public async ValueTask DisposeAsync()
    {
        if (_disposed) return;
        _disposed = true;

        _cts.Cancel();
        await _flushTimer.DisposeAsync();
        await _heartbeatTimer.DisposeAsync();

        await FlushEventsAsync();

        _httpClient.Dispose();
        _flushLock.Dispose();
        _cts.Dispose();
    }
}
