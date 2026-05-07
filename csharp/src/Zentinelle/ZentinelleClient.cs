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
    private const string ApiBasePath = "/api/zentinelle/v1";

    private readonly HttpClient _httpClient;
    private readonly bool _ownsHttpClient;
    private readonly ZentinelleOptions _options;
    private readonly ILogger<ZentinelleClient> _logger;
    private readonly CircuitBreaker _circuitBreaker;
    private readonly ConcurrentQueue<Event> _eventBuffer;
    private readonly int _maxBufferSize;
    private readonly Timer _flushTimer;
    private readonly Timer _heartbeatTimer;
    private readonly SemaphoreSlim _flushLock = new(1, 1);
    private readonly CancellationTokenSource _cts = new();
    private readonly object _stateLock = new();
    private readonly object _configCacheLock = new();
    private readonly object _secretsCacheLock = new();
    private readonly string _endpoint;

    private string _apiKey;
    private string? _agentId;
    private bool _registered;
    private ConfigResult? _cachedConfig;
    private DateTime _configCacheTime;
    private Dictionary<string, string>? _secretsCache;
    private DateTime _secretsCacheTime;
    private int _disposed;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = false
    };

    /// <summary>
    /// Creates a new Zentinelle client with the specified options.
    /// </summary>
    public ZentinelleClient(
        ZentinelleOptions options,
        ILogger<ZentinelleClient>? logger = null,
        HttpClient? httpClient = null)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));
        _logger = logger ?? NullLogger<ZentinelleClient>.Instance;

        if (string.IsNullOrWhiteSpace(options.ApiKey) || options.ApiKey.Length < 10)
        {
            throw new ArgumentException("ApiKey is required and must be valid", nameof(options));
        }

        var validPrefixes = new[] { "sk_agent_", "sk_test_", "sk_live_", "znt_", "bt_" };
        if (!validPrefixes.Any(prefix => options.ApiKey.StartsWith(prefix, StringComparison.Ordinal)))
        {
            _logger.LogWarning(
                "API key does not match expected format (sk_agent_*, sk_test_*, sk_live_*, znt_*, bt_*). " +
                "This may indicate an invalid key.");
        }

        if (string.IsNullOrWhiteSpace(options.AgentType))
        {
            throw new ArgumentException("AgentType is required", nameof(options));
        }

        _endpoint = (string.IsNullOrWhiteSpace(options.BaseUrl) ? "https://api.zentinelle.ai" : options.BaseUrl)
            .TrimEnd('/');
        var isLocalhost = _endpoint.Contains("localhost", StringComparison.OrdinalIgnoreCase) ||
            _endpoint.Contains("127.0.0.1", StringComparison.OrdinalIgnoreCase);
        if (!_endpoint.StartsWith("https://", StringComparison.OrdinalIgnoreCase) &&
            !isLocalhost)
        {
            throw new ArgumentException("BaseUrl must use HTTPS for security (localhost excepted)", nameof(options));
        }

        _apiKey = options.ApiKey;
        _agentId = options.AgentId;
        _registered = !string.IsNullOrWhiteSpace(_agentId) && !_apiKey.StartsWith("bt_", StringComparison.Ordinal);

        _ownsHttpClient = httpClient == null;
        _httpClient = httpClient ?? new HttpClient();

        if (_httpClient.BaseAddress == null)
        {
            _httpClient.BaseAddress = new Uri(_endpoint);
        }
        if (!_httpClient.DefaultRequestHeaders.UserAgent.Any())
        {
            _httpClient.DefaultRequestHeaders.UserAgent.ParseAdd("zentinelle-csharp/0.1.0");
        }
        if (!_httpClient.DefaultRequestHeaders.Accept.Any())
        {
            _httpClient.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        }
        if (_ownsHttpClient)
        {
            _httpClient.Timeout = options.Timeout;
        }

        _circuitBreaker = new CircuitBreaker(
            options.CircuitBreakerThreshold,
            options.CircuitBreakerRecovery);

        _eventBuffer = new ConcurrentQueue<Event>();
        _maxBufferSize = Math.Max(options.MaxBatchSize * 10, 1000);

        _flushTimer = new Timer(
            _ => SafeFlushEventsAsync(),
            null,
            options.FlushInterval,
            options.FlushInterval);

        _heartbeatTimer = new Timer(
            _ => SafeSendHeartbeatAsync(),
            null,
            options.HeartbeatInterval,
            options.HeartbeatInterval);
    }

    private async void SafeFlushEventsAsync()
    {
        if (Volatile.Read(ref _disposed) != 0 || _cts.Token.IsCancellationRequested) return;

        try
        {
            await FlushEventsAsync(_cts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // Expected during shutdown.
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Background event flush failed");
        }
    }

    private async void SafeSendHeartbeatAsync()
    {
        if (Volatile.Read(ref _disposed) != 0 || _cts.Token.IsCancellationRequested) return;

        try
        {
            var result = await HeartbeatAsync(cancellationToken: _cts.Token).ConfigureAwait(false);
            if (result?.HasConfigChangeSignal == true)
            {
                await GetConfigAsync(forceRefresh: true, cancellationToken: _cts.Token).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException)
        {
            // Expected during shutdown.
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Background heartbeat failed");
        }
    }

    /// <summary>
    /// Creates a new Zentinelle client using environment variables.
    /// </summary>
    public static ZentinelleClient FromEnvironment(ILogger<ZentinelleClient>? logger = null)
    {
        var apiKey = Environment.GetEnvironmentVariable("ZENTINELLE_API_KEY")
            ?? throw new InvalidOperationException("ZENTINELLE_API_KEY environment variable not set");
        var agentType = Environment.GetEnvironmentVariable("ZENTINELLE_AGENT_TYPE")
            ?? throw new InvalidOperationException("ZENTINELLE_AGENT_TYPE environment variable not set");

        return new ZentinelleClient(new ZentinelleOptions
        {
            ApiKey = apiKey,
            AgentId = Environment.GetEnvironmentVariable("ZENTINELLE_AGENT_ID"),
            AgentType = agentType,
            OrgId = Environment.GetEnvironmentVariable("ZENTINELLE_ORG_ID")
        }, logger);
    }

    /// <summary>
    /// Registers the agent with Zentinelle.
    /// </summary>
    public async Task<RegisterResult> RegisterAsync(
        RegisterOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        var request = new
        {
            agent_id = _agentId,
            agent_type = _options.AgentType,
            capabilities = options?.Capabilities ?? new List<string>(),
            metadata = options?.Metadata ?? new Dictionary<string, object>(),
            name = options?.Name
        };

        var response = await SendRequestAsync<RegisterResult>(
            HttpMethod.Post,
            "/register",
            request,
            cancellationToken,
            forRegistration: true).ConfigureAwait(false);

        if (string.IsNullOrWhiteSpace(response.AgentId))
        {
            throw new ZentinelleException("Invalid response: missing required 'agent_id'");
        }

        response.Config ??= new Dictionary<string, object>();
        response.Policies ??= new List<PolicyConfig>();

        lock (_stateLock)
        {
            _agentId = response.AgentId;
            if (!string.IsNullOrWhiteSpace(response.ApiKey))
            {
                _apiKey = response.ApiKey!;
            }
            _registered = true;
        }

        lock (_configCacheLock)
        {
            _cachedConfig = new ConfigResult
            {
                AgentId = response.AgentId,
                Config = CopyDictionary(response.Config),
                Policies = ClonePolicies(response.Policies),
                UpdatedAt = DateTime.UtcNow
            };
            _configCacheTime = DateTime.UtcNow;
        }

        _logger.LogInformation("Registered agent {AgentId}", response.AgentId);

        return CloneRegisterResult(response);
    }

    /// <summary>
    /// Evaluates an action against configured policies.
    /// </summary>
    public async Task<EvaluateResult> EvaluateAsync(
        string action,
        EvaluateOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(action))
        {
            throw new ArgumentException("Action cannot be null or empty", nameof(action));
        }

        var agentId = RequireAgentId();
        var request = new
        {
            agent_id = agentId,
            action,
            user_id = options?.UserId,
            context = options?.Context ?? new Dictionary<string, object>()
        };

        var result = await SendRequestAsync<EvaluateResult>(
            HttpMethod.Post,
            "/evaluate",
            request,
            cancellationToken,
            validateAllowedField: true).ConfigureAwait(false);

        result.PoliciesEvaluated ??= new List<PolicyEvaluation>();
        result.Warnings ??= new List<string>();
        result.Context ??= new Dictionary<string, object>();

        return result;
    }

    /// <summary>
    /// Evaluates an action synchronously.
    /// </summary>
    public EvaluateResult Evaluate(string action, EvaluateOptions? options = null)
    {
        return EvaluateAsync(action, options).GetAwaiter().GetResult();
    }

    /// <summary>
    /// Checks if a tool call is allowed.
    /// </summary>
    public Task<EvaluateResult> CanCallToolAsync(
        string toolName,
        string? userId = null,
        CancellationToken cancellationToken = default)
    {
        return EvaluateAsync(
            "tool_call",
            new EvaluateOptions
            {
                UserId = userId,
                Context = new Dictionary<string, object> { ["tool"] = toolName }
            },
            cancellationToken);
    }

    /// <summary>
    /// Checks if a model request is allowed.
    /// </summary>
    public Task<EvaluateResult> CanUseModelAsync(
        string model,
        string provider = "openai",
        CancellationToken cancellationToken = default)
    {
        return EvaluateAsync(
            "model_request",
            new EvaluateOptions
            {
                Context = new Dictionary<string, object>
                {
                    ["model"] = model,
                    ["provider"] = provider
                }
            },
            cancellationToken);
    }

    /// <summary>
    /// Emits an event for tracking.
    /// </summary>
    public void Emit(Event evt)
    {
        if (evt == null)
        {
            throw new ArgumentNullException(nameof(evt));
        }

        evt.Timestamp ??= DateTime.UtcNow;

        lock (_eventBuffer)
        {
            if (_eventBuffer.Count >= _maxBufferSize)
            {
                var toDrop = Math.Max(1, _eventBuffer.Count - _maxBufferSize + 10);
                var dropped = 0;
                for (var i = 0; i < toDrop && _eventBuffer.TryDequeue(out _); i++)
                {
                    dropped++;
                }
                if (dropped > 0)
                {
                    _logger.LogWarning("Event buffer at max capacity, dropped {Count} oldest events", dropped);
                }
            }

            _eventBuffer.Enqueue(evt);
        }

        if (_eventBuffer.Count >= _options.MaxBatchSize)
        {
            SafeFlushEventsAsync();
        }
    }

    /// <summary>
    /// Emits an event asynchronously and waits for confirmation.
    /// </summary>
    public async Task EmitAsync(Event evt, CancellationToken cancellationToken = default)
    {
        Emit(evt);
        await FlushEventsAsync(cancellationToken).ConfigureAwait(false);
    }

    /// <summary>
    /// Convenience wrapper for tool-call events.
    /// </summary>
    public void EmitToolCall(string toolName, string? userId = null, long? durationMs = null)
    {
        var evt = Event.ToolCall(toolName, success: true);
        evt.UserId = userId;
        if (durationMs.HasValue)
        {
            evt.Payload["duration_ms"] = durationMs.Value;
        }
        Emit(evt);
    }

    /// <summary>
    /// Convenience wrapper for model-request events.
    /// </summary>
    public void EmitModelRequest(
        string provider,
        string model,
        int inputTokens,
        int outputTokens,
        string? userId = null,
        long? durationMs = null,
        decimal? estimatedCost = null)
    {
        var evt = Event.ModelRequest(model, new ModelUsage
        {
            Provider = provider,
            Model = model,
            InputTokens = inputTokens,
            OutputTokens = outputTokens,
            EstimatedCost = estimatedCost
        });
        evt.UserId = userId;
        if (durationMs.HasValue)
        {
            evt.Payload["duration_ms"] = durationMs.Value;
        }
        Emit(evt);
    }

    /// <summary>
    /// Tracks model usage for cost policy evaluation.
    /// </summary>
    public void TrackUsage(ModelUsage usage)
    {
        Emit(new Event
        {
            Type = "model_usage",
            Category = EventCategory.Telemetry,
            Payload = new Dictionary<string, object>
            {
                ["provider"] = usage.Provider ?? string.Empty,
                ["model"] = usage.Model ?? string.Empty,
                ["input_tokens"] = usage.InputTokens,
                ["output_tokens"] = usage.OutputTokens,
                ["estimated_cost"] = usage.EstimatedCost ?? 0m
            }
        });
    }

    /// <summary>
    /// Gets the agent configuration from Zentinelle.
    /// </summary>
    public async Task<ConfigResult> GetConfigAsync(
        bool forceRefresh = false,
        CancellationToken cancellationToken = default)
    {
        var agentId = RequireAgentId();

        lock (_configCacheLock)
        {
            if (!forceRefresh &&
                _cachedConfig != null &&
                DateTime.UtcNow - _configCacheTime < _options.ConfigCacheDuration)
            {
                return CloneConfigResult(_cachedConfig);
            }
        }

        var response = await SendRequestAsync<ConfigResult>(
            HttpMethod.Get,
            $"/config/{agentId}",
            null,
            cancellationToken).ConfigureAwait(false);

        response.AgentId = string.IsNullOrWhiteSpace(response.AgentId) ? agentId : response.AgentId;
        response.Config ??= new Dictionary<string, object>();
        response.Policies ??= new List<PolicyConfig>();
        if (response.UpdatedAt == default)
        {
            response.UpdatedAt = DateTime.UtcNow;
        }

        lock (_configCacheLock)
        {
            _cachedConfig = CloneConfigResult(response);
            _configCacheTime = DateTime.UtcNow;
        }

        return CloneConfigResult(response);
    }

    /// <summary>
    /// Gets secrets configured for this agent.
    /// </summary>
    public async Task<Dictionary<string, string>> GetSecretsAsync(
        bool forceRefresh = false,
        CancellationToken cancellationToken = default)
    {
        RequireAgentId();

        lock (_secretsCacheLock)
        {
            if (!forceRefresh &&
                _secretsCache != null &&
                DateTime.UtcNow - _secretsCacheTime < _options.SecretsCacheDuration)
            {
                return CopyStringDictionary(_secretsCache);
            }
        }

        var agentId = RequireAgentId();
        var response = await SendRequestAsync<SecretsEnvelope>(
            HttpMethod.Get,
            $"/secrets/{agentId}",
            null,
            cancellationToken).ConfigureAwait(false);

        var secrets = CopyStringDictionary(response.Secrets);
        lock (_secretsCacheLock)
        {
            _secretsCache = CopyStringDictionary(secrets);
            _secretsCacheTime = DateTime.UtcNow;
        }

        return secrets;
    }

    /// <summary>
    /// Gets a single secret value.
    /// </summary>
    public async Task<string?> GetSecretAsync(
        string key,
        string? defaultValue = null,
        CancellationToken cancellationToken = default)
    {
        var secrets = await GetSecretsAsync(cancellationToken: cancellationToken).ConfigureAwait(false);
        return secrets.TryGetValue(key, out var value) ? value : defaultValue;
    }

    /// <summary>
    /// Flushes any buffered events immediately.
    /// </summary>
    public async Task FlushAsync(CancellationToken cancellationToken = default)
    {
        await FlushEventsAsync(cancellationToken).ConfigureAwait(false);
    }

    private async Task FlushEventsAsync(CancellationToken cancellationToken = default)
    {
        if (_eventBuffer.IsEmpty)
        {
            return;
        }

        var agentId = CurrentAgentId;
        if (string.IsNullOrWhiteSpace(agentId))
        {
            return;
        }

        if (!await _flushLock.WaitAsync(0, cancellationToken).ConfigureAwait(false))
        {
            return;
        }

        List<Event>? events = null;
        try
        {
            events = new List<Event>();
            while (events.Count < _options.MaxBatchSize && _eventBuffer.TryDequeue(out var evt))
            {
                events.Add(evt);
            }

            if (events.Count == 0)
            {
                return;
            }

            var request = new
            {
                agent_id = agentId,
                events = events.Select(evt => evt.ToApiPayload()).ToList()
            };

            await SendRequestAsync<object>(
                HttpMethod.Post,
                "/events",
                request,
                cancellationToken).ConfigureAwait(false);

            _logger.LogDebug("Flushed {Count} events", events.Count);
            events = null;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to flush events");

            if (events != null && events.Count > 0)
            {
                lock (_eventBuffer)
                {
                    if (_eventBuffer.Count + events.Count <= _maxBufferSize)
                    {
                        var newBuffer = new ConcurrentQueue<Event>(events);
                        while (_eventBuffer.TryDequeue(out var existing))
                        {
                            newBuffer.Enqueue(existing);
                        }
                        while (newBuffer.TryDequeue(out var evt))
                        {
                            _eventBuffer.Enqueue(evt);
                        }
                    }
                    else
                    {
                        _logger.LogWarning("Failed to flush {Count} events and buffer is full, events dropped", events.Count);
                    }
                }
            }
        }
        finally
        {
            _flushLock.Release();
        }
    }

    /// <summary>
    /// Sends a heartbeat to Zentinelle.
    /// </summary>
    public async Task<HeartbeatResult?> HeartbeatAsync(
        string status = "healthy",
        Dictionary<string, object>? metrics = null,
        CancellationToken cancellationToken = default)
    {
        if (!IsRegistered)
        {
            return null;
        }

        var agentId = CurrentAgentId;
        if (string.IsNullOrWhiteSpace(agentId))
        {
            return null;
        }

        var response = await SendRequestAsync<HeartbeatResult>(
            HttpMethod.Post,
            "/heartbeat",
            new
            {
                agent_id = agentId,
                status = string.IsNullOrWhiteSpace(status) ? "healthy" : status,
                metrics = metrics ?? new Dictionary<string, object>()
            },
            cancellationToken).ConfigureAwait(false);

        if (!response.Acknowledged &&
            !response.ConfigChanged &&
            !response.DriftDetected &&
            !response.SyncRequired &&
            response.NextHeartbeatSeconds == 0)
        {
            response.Acknowledged = true;
        }
        if (response.NextHeartbeatSeconds == 0)
        {
            response.NextHeartbeatSeconds = 60;
        }

        return response;
    }

    private async Task<T> SendRequestAsync<T>(
        HttpMethod method,
        string path,
        object? body,
        CancellationToken cancellationToken,
        bool validateAllowedField = false,
        bool forRegistration = false)
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
                using var request = new HttpRequestMessage(method, $"{ApiBasePath}{path}");
                AddAuthHeaders(request, forRegistration);

                if (body != null)
                {
                    var json = JsonSerializer.Serialize(body, JsonOptions);
                    request.Content = new StringContent(json, Encoding.UTF8, "application/json");
                }

                using var response = await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);

                if (response.IsSuccessStatusCode)
                {
                    _circuitBreaker.RecordSuccess();
                    var content = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                    if (string.IsNullOrWhiteSpace(content))
                    {
                        return default!;
                    }

                    if (validateAllowedField)
                    {
                        using var doc = JsonDocument.Parse(content);
                        var isFailOpen = doc.RootElement.TryGetProperty("fail_open", out var failOpenProp) &&
                            failOpenProp.ValueKind == JsonValueKind.True;
                        if (!isFailOpen && !doc.RootElement.TryGetProperty("allowed", out _))
                        {
                            throw new ZentinelleException("Invalid response: missing required 'allowed' field");
                        }
                    }

                    return JsonSerializer.Deserialize<T>(content, JsonOptions)!;
                }

                var statusCode = (int)response.StatusCode;
                var errorContent = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);

                if (statusCode == 401)
                {
                    throw new AuthenticationException("Invalid API key");
                }
                if (statusCode == 403)
                {
                    throw new AuthenticationException("Access denied");
                }
                if (statusCode == 429)
                {
                    _circuitBreaker.RecordSuccess();
                    var retryAfter = response.Headers.RetryAfter?.Delta?.Seconds ?? 60;
                    throw new RateLimitException("Rate limit exceeded", (int)retryAfter);
                }
                if (statusCode >= 500 && retries < _options.MaxRetries)
                {
                    lastException = new ConnectionException($"Server error: {statusCode}");
                    _circuitBreaker.RecordFailure();
                    retries++;
                    await Task.Delay(GetBackoffDelay(retries), cancellationToken).ConfigureAwait(false);
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
                    await Task.Delay(GetBackoffDelay(retries), cancellationToken).ConfigureAwait(false);
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
                    await Task.Delay(GetBackoffDelay(retries), cancellationToken).ConfigureAwait(false);
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

    private void AddAuthHeaders(HttpRequestMessage request, bool forRegistration)
    {
        string apiKey;
        string? orgId;
        lock (_stateLock)
        {
            apiKey = _apiKey;
            orgId = _options.OrgId;
        }

        if (forRegistration && apiKey.StartsWith("bt_", StringComparison.Ordinal))
        {
            request.Headers.Add("X-Zentinelle-Bootstrap", apiKey);
        }
        else
        {
            request.Headers.Add("X-Zentinelle-Key", apiKey);
        }

        if (!string.IsNullOrWhiteSpace(orgId))
        {
            request.Headers.Add("X-Zentinelle-Org", orgId);
        }
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
                FailOpen = true,
                PoliciesEvaluated = new List<PolicyEvaluation>(),
                Warnings = new List<string> { "Service unavailable - fail-open mode active" },
                Context = new Dictionary<string, object>()
            };
        }
        return default!;
    }

    private string RequireAgentId()
    {
        lock (_stateLock)
        {
            if (string.IsNullOrWhiteSpace(_agentId))
            {
                throw new ZentinelleException(
                    "Agent not registered. Call RegisterAsync() first or provide AgentId in the constructor.");
            }
            return _agentId!;
        }
    }

    private string? CurrentAgentId
    {
        get
        {
            lock (_stateLock)
            {
                return _agentId;
            }
        }
    }

    /// <summary>
    /// Whether the client currently has a registered runtime identity.
    /// </summary>
    public bool IsRegistered
    {
        get
        {
            lock (_stateLock)
            {
                return _registered;
            }
        }
    }

    /// <summary>
    /// Returns a string representation of the client with masked API key.
    /// </summary>
    public override string ToString()
    {
        string apiKey;
        string? agentId;
        lock (_stateLock)
        {
            apiKey = _apiKey;
            agentId = _agentId;
        }

        var maskedKey = apiKey.Length > 12
            ? apiKey[..8] + "..." + apiKey[^4..]
            : "***";
        return $"ZentinelleClient(agent_id=\"{agentId}\", agent_type=\"{_options.AgentType}\", endpoint=\"{_endpoint}\", api_key=\"{maskedKey}\")";
    }

    /// <inheritdoc />
    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 1) return;

        _flushTimer.Dispose();
        _heartbeatTimer.Dispose();

        try
        {
            using var flushCts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            FlushEventsAsync(flushCts.Token).GetAwaiter().GetResult();
        }
        catch (Exception)
        {
            // Ignore flush errors during disposal.
        }

        _cts.Cancel();

        if (_ownsHttpClient)
        {
            _httpClient.Dispose();
        }
        _flushLock.Dispose();
        _cts.Dispose();
    }

    /// <inheritdoc />
    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 1) return;

        await _flushTimer.DisposeAsync().ConfigureAwait(false);
        await _heartbeatTimer.DisposeAsync().ConfigureAwait(false);

        try
        {
            using var flushCts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            await FlushEventsAsync(flushCts.Token).ConfigureAwait(false);
        }
        catch (Exception)
        {
            // Ignore flush errors during disposal.
        }

        _cts.Cancel();

        if (_ownsHttpClient)
        {
            _httpClient.Dispose();
        }
        _flushLock.Dispose();
        _cts.Dispose();
    }

    private static RegisterResult CloneRegisterResult(RegisterResult source)
    {
        return new RegisterResult
        {
            AgentId = source.AgentId,
            ApiKey = source.ApiKey,
            Config = CopyDictionary(source.Config),
            Policies = ClonePolicies(source.Policies)
        };
    }

    private static ConfigResult CloneConfigResult(ConfigResult source)
    {
        return new ConfigResult
        {
            AgentId = source.AgentId,
            Config = CopyDictionary(source.Config),
            Policies = ClonePolicies(source.Policies),
            UpdatedAt = source.UpdatedAt
        };
    }

    private static List<PolicyConfig> ClonePolicies(IEnumerable<PolicyConfig>? policies)
    {
        if (policies == null)
        {
            return new List<PolicyConfig>();
        }

        return policies.Select(policy => new PolicyConfig
        {
            Id = policy.Id,
            Name = policy.Name,
            Type = policy.Type,
            Enforcement = policy.Enforcement,
            Config = CopyDictionary(policy.Config),
            Priority = policy.Priority
        }).ToList();
    }

    private static Dictionary<string, object> CopyDictionary(Dictionary<string, object>? source)
    {
        return source == null
            ? new Dictionary<string, object>()
            : new Dictionary<string, object>(source);
    }

    private static Dictionary<string, string> CopyStringDictionary(Dictionary<string, string>? source)
    {
        return source == null
            ? new Dictionary<string, string>()
            : new Dictionary<string, string>(source);
    }

    private sealed class SecretsEnvelope
    {
        public Dictionary<string, string>? Secrets { get; set; }
    }
}
