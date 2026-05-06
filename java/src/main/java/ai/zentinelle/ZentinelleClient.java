package ai.zentinelle;

import ai.zentinelle.model.*;
import ai.zentinelle.exception.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import okhttp3.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Zentinelle SDK client for AI agent governance.
 *
 * <p>Provides policy enforcement, secrets management, and observability
 * for AI agents across any Java framework.
 *
 * <h2>Example Usage:</h2>
 * <pre>{@code
 * ZentinelleClient client = ZentinelleClient.builder()
 *     .apiKey("sk_agent_...")
 *     .agentType("java-agent")
 *     .build();
 *
 * // Register on startup
 * RegisterResult result = client.register(RegisterOptions.builder()
 *     .capabilities(List.of("chat", "tools"))
 *     .build());
 *
 * // Evaluate policies
 * EvaluateResult eval = client.evaluate("tool_call", EvaluateOptions.builder()
 *     .userId("user123")
 *     .context(Map.of("tool", "web_search"))
 *     .build());
 *
 * if (!eval.isAllowed()) {
 *     throw new PolicyViolationException(eval.getReason(), eval);
 * }
 *
 * // Track usage
 * client.trackUsage(ModelUsage.builder()
 *     .provider("openai")
 *     .model("gpt-4o")
 *     .inputTokens(100)
 *     .outputTokens(50)
 *     .build());
 *
 * // Shutdown gracefully
 * client.shutdown();
 * }</pre>
 *
 * @author Calliope Labs
 * @since 0.1.0
 */
public class ZentinelleClient implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(ZentinelleClient.class);
    private static final String DEFAULT_ENDPOINT = "https://api.zentinelle.ai";
    private static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(30);
    private static final int DEFAULT_MAX_RETRIES = 3;
    private static final int DEFAULT_BUFFER_SIZE = 100;
    private static final Duration DEFAULT_FLUSH_INTERVAL = Duration.ofSeconds(5);
    private static final String API_BASE_PATH = "/api/zentinelle/v1";

    private volatile String apiKey;
    private final String agentType;
    private final String endpoint;
    private final String orgId;
    private final Duration timeout;
    private final int maxRetries;
    private final boolean failOpen;
    private final int bufferSize;

    private final OkHttpClient httpClient;
    private final ObjectMapper objectMapper;
    private final CircuitBreaker circuitBreaker;

    private volatile String agentId;  // Volatile for thread-safe reads
    private final AtomicBoolean registered = new AtomicBoolean(false);
    private final Object registrationLock = new Object();  // Lock for atomic registration updates
    private final List<Event> eventBuffer = Collections.synchronizedList(new ArrayList<>());
    private final int maxBufferSize; // Maximum buffer size to prevent memory leaks
    private final ScheduledExecutorService scheduler;
    private volatile boolean shutdown = false;

    // Secrets cache
    private volatile Map<String, String> secretsCache = null;
    private volatile Instant secretsCacheTime = null;
    private final Duration secretsCacheTtl;
    private final Object secretsCacheLock = new Object();
    private volatile Map<String, Object> configCache = null;
    private volatile Instant configCacheTime = null;
    private volatile List<PolicyConfig> policiesCache = List.of();
    private final Duration configCacheTtl;
    private final Object configCacheLock = new Object();

    private ZentinelleClient(Builder builder) {
        this.apiKey = Objects.requireNonNull(builder.apiKey, "apiKey is required");
        if (this.apiKey.length() < 10) {
            throw new IllegalArgumentException("apiKey format is invalid");
        }
        // Validate API key format (should start with known prefixes)
        if (!this.apiKey.startsWith("sk_agent_") && !this.apiKey.startsWith("sk_test_") &&
            !this.apiKey.startsWith("sk_live_") && !this.apiKey.startsWith("znt_") &&
            !this.apiKey.startsWith("bt_")) {
            log.warn("API key does not match expected format (sk_agent_*, sk_test_*, sk_live_*, znt_*, bt_*). " +
                "This may indicate an invalid key.");
        }
        this.agentType = Objects.requireNonNull(builder.agentType, "agentType is required");
        this.endpoint = (builder.endpoint != null ? builder.endpoint : DEFAULT_ENDPOINT).replaceAll("/+$", "");
        // Enforce HTTPS for security (API keys are transmitted in headers)
        if (!this.endpoint.startsWith("https://") && !isLocalEndpoint(this.endpoint)) {
            throw new IllegalArgumentException("endpoint must use HTTPS for security");
        }
        this.orgId = builder.orgId;
        this.timeout = builder.timeout != null ? builder.timeout : DEFAULT_TIMEOUT;
        this.maxRetries = builder.maxRetries > 0 ? builder.maxRetries : DEFAULT_MAX_RETRIES;
        this.failOpen = builder.failOpen;
        this.bufferSize = builder.bufferSize > 0 ? builder.bufferSize : DEFAULT_BUFFER_SIZE;
        // Maximum buffer size to prevent memory leaks (10x normal or 1000, whichever is larger)
        this.maxBufferSize = Math.max(this.bufferSize * 10, 1000);
        this.agentId = builder.agentId;

        this.httpClient = new OkHttpClient.Builder()
            .connectTimeout(timeout)
            .readTimeout(timeout)
            .writeTimeout(timeout)
            .build();

        this.objectMapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

        this.circuitBreaker = new CircuitBreaker(
            builder.circuitBreakerThreshold > 0 ? builder.circuitBreakerThreshold : 5,
            builder.circuitBreakerTimeout != null ? builder.circuitBreakerTimeout : Duration.ofSeconds(30)
        );

        // Secrets cache TTL (default 60 seconds)
        this.secretsCacheTtl = builder.secretsCacheTtl != null ? builder.secretsCacheTtl : Duration.ofSeconds(60);
        this.configCacheTtl = builder.configCacheTtl != null ? builder.configCacheTtl : Duration.ofSeconds(300);

        // Start background flush
        Duration flushInterval = builder.flushInterval != null ? builder.flushInterval : DEFAULT_FLUSH_INTERVAL;
        this.scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "zentinelle-flush");
            t.setDaemon(true);
            return t;
        });
        this.scheduler.scheduleAtFixedRate(
            this::flushEventsAsync,
            flushInterval.toMillis(),
            flushInterval.toMillis(),
            TimeUnit.MILLISECONDS
        );
    }

    /**
     * Creates a new builder for ZentinelleClient.
     *
     * @return a new Builder instance
     */
    public static Builder builder() {
        return new Builder();
    }

    /**
     * Registers the agent with Zentinelle.
     *
     * @param options registration options
     * @return registration result containing agent ID and initial config
     * @throws ZentinelleException if registration fails
     */
    public RegisterResult register(RegisterOptions options) throws ZentinelleException {
        RegisterOptions registerOptions = options != null ? options : RegisterOptions.builder().build();
        Map<String, Object> body = new HashMap<>();
        body.put("agent_id", agentId);
        body.put("agent_type", agentType);
        body.put("capabilities", registerOptions.getCapabilities());
        body.put("metadata", registerOptions.getMetadata());
        body.put("name", registerOptions.getName());

        Map<String, Object> response = request("POST", "/register", body, true);
        Map<String, Object> config = copyMap(castToMap(response.get("config")));
        List<PolicyConfig> policies = copyPolicies(parsePolicies(response.get("policies")));

        // Atomically update agentId and registered flag to prevent race conditions
        synchronized (registrationLock) {
            this.agentId = (String) response.get("agent_id");
            if (response.get("api_key") instanceof String runtimeApiKey && !runtimeApiKey.isBlank()) {
                this.apiKey = runtimeApiKey;
            }
            this.registered.set(true);
        }

        synchronized (configCacheLock) {
            this.configCache = config;
            this.configCacheTime = Instant.now();
            this.policiesCache = policies;
        }

        log.info("Registered agent: {}", agentId);

        return RegisterResult.builder()
            .agentId(agentId)
            .apiKey((String) response.get("api_key"))
            .config(config)
            .policies(copyPolicies(policies))
            .build();
    }

    /**
     * Evaluates policies for an action.
     *
     * @param action the action to evaluate
     * @param options evaluation options
     * @return evaluation result
     * @throws ZentinelleException if evaluation fails
     */
    public EvaluateResult evaluate(String action, EvaluateOptions options) throws ZentinelleException {
        requireAgentId();
        Map<String, Object> body = new HashMap<>();
        body.put("agent_id", agentId);
        body.put("action", action);
        body.put("user_id", options.getUserId());
        body.put("context", options.getContext());

        Map<String, Object> response = requestForEvaluate("POST", "/evaluate", body);

        // Check for fail-open response
        boolean isFailOpen = Boolean.TRUE.equals(response.get("fail_open"));

        // Critical: validate that 'allowed' field is present and is a Boolean (unless fail-open)
        // Never default to true - this would bypass security
        Object allowedObj = response.get("allowed");
        if (!isFailOpen) {
            if (allowedObj == null) {
                throw new ZentinelleException("Invalid response: missing required 'allowed' field");
            }
            if (!(allowedObj instanceof Boolean)) {
                throw new ZentinelleException("Invalid response: 'allowed' field must be a boolean, got: " +
                    (allowedObj == null ? "null" : allowedObj.getClass().getSimpleName()));
            }
        }

        boolean allowed = isFailOpen ? true : (Boolean) allowedObj;

        return EvaluateResult.builder()
            .allowed(allowed)
            .reason((String) response.get("reason"))
            .policiesEvaluated(parsePolicyEvaluations(response.get("policies_evaluated")))
            .warnings(castToStringList(response.get("warnings")))
            .context(castToMap(response.get("context")))
            .failOpen(isFailOpen)
            .build();
    }

    /**
     * Checks if a tool can be called.
     */
    public EvaluateResult canCallTool(String toolName, String userId) throws ZentinelleException {
        return evaluate("tool_call", EvaluateOptions.builder()
            .userId(userId)
            .context(Map.of("tool", toolName))
            .build());
    }

    /**
     * Checks if a model can be used.
     */
    public EvaluateResult canUseModel(String model, String provider) throws ZentinelleException {
        return evaluate("model_request", EvaluateOptions.builder()
            .context(Map.of("model", model, "provider", provider))
            .build());
    }

    /**
     * Retrieves config and policies for the agent (cached).
     */
    public ConfigResult getConfig() throws ZentinelleException {
        return getConfig(false);
    }

    /**
     * Retrieves config and policies for the agent with optional cache bypass.
     */
    public ConfigResult getConfig(boolean forceRefresh) throws ZentinelleException {
        requireAgentId();

        if (!forceRefresh) {
            synchronized (configCacheLock) {
                if (configCache != null && configCacheTime != null &&
                    Duration.between(configCacheTime, Instant.now()).compareTo(configCacheTtl) < 0) {
                    return ConfigResult.builder()
                        .agentId(agentId)
                        .config(copyMap(configCache))
                        .policies(copyPolicies(policiesCache))
                        .updatedAt(configCacheTime)
                        .build();
                }
            }
        }

        Map<String, Object> response = request("GET", "/config/" + agentId, null);
        Map<String, Object> config = copyMap(castToMap(response.get("config")));
        List<PolicyConfig> policies = copyPolicies(parsePolicies(response.get("policies")));
        Instant updatedAt = parseInstant(response.get("updated_at"), Instant.now());
        String responseAgentId = response.get("agent_id") instanceof String value ? value : agentId;

        synchronized (configCacheLock) {
            configCache = config;
            configCacheTime = updatedAt;
            policiesCache = policies;
        }

        return ConfigResult.builder()
            .agentId(responseAgentId)
            .config(copyMap(config))
            .policies(copyPolicies(policies))
            .updatedAt(updatedAt)
            .build();
    }

    /**
     * Retrieves secrets for the agent (cached).
     */
    public Map<String, String> getSecrets() throws ZentinelleException {
        return getSecrets(false);
    }

    /**
     * Retrieves secrets for the agent with optional cache bypass.
     *
     * @param forceRefresh if true, bypasses the cache and fetches fresh secrets
     * @return map of secret name to value
     */
    public Map<String, String> getSecrets(boolean forceRefresh) throws ZentinelleException {
        requireAgentId();
        // Thread-safe cache check
        if (!forceRefresh) {
            synchronized (secretsCacheLock) {
                if (secretsCache != null && secretsCacheTime != null &&
                    Duration.between(secretsCacheTime, Instant.now()).compareTo(secretsCacheTtl) < 0) {
                    // Return a copy to prevent modification
                    return new HashMap<>(secretsCache);
                }
            }
        }

        Map<String, Object> response = request("GET", "/secrets/" + agentId, null);
        Map<String, String> secrets = copyStringMap(castToStringMap(response.get("secrets")));

        // Update cache
        synchronized (secretsCacheLock) {
            secretsCache = secrets;
            secretsCacheTime = Instant.now();
        }

        // Return a copy to prevent modification
        return new HashMap<>(secrets);
    }

    /**
     * Tracks model usage for cost policies.
     */
    public void trackUsage(ModelUsage usage) {
        emit("model_usage", Map.of(
            "provider", usage.getProvider(),
            "model", usage.getModel(),
            "input_tokens", usage.getInputTokens(),
            "output_tokens", usage.getOutputTokens(),
            "estimated_cost", usage.getEstimatedCost()
        ), EmitOptions.builder().category(EventCategory.TELEMETRY).build());
    }

    /**
     * Emits an event (buffered).
     */
    public void emit(String eventType, Map<String, Object> payload, EmitOptions options) {
        Event event = Event.builder()
            .type(eventType)
            .category(options.getCategory() != null ? options.getCategory() : EventCategory.TELEMETRY)
            .payload(payload)
            .timestamp(Instant.now())
            .userId(options.getUserId())
            .build();

        synchronized (eventBuffer) {
            // Enforce max buffer size to prevent memory leaks
            if (eventBuffer.size() >= maxBufferSize) {
                int dropped = eventBuffer.size() - maxBufferSize + 1;
                eventBuffer.subList(0, dropped).clear();  // O(n) instead of O(n²)
                log.warn("Event buffer at max capacity, dropped {} oldest events", dropped);
            }
            eventBuffer.add(event);
        }
        // Note: Flushing is handled by the scheduled executor to avoid race conditions.
        // We don't call flushEventsAsync() here since it could cause concurrent flushes
        // with the scheduled task. The scheduled task runs every flushInterval.
    }

    /**
     * Emits a tool call event.
     */
    public void emitToolCall(String toolName, String userId, long durationMs) {
        emit("tool_call", Map.of(
            "tool", toolName,
            "duration_ms", durationMs
        ), EmitOptions.builder()
            .category(EventCategory.AUDIT)
            .userId(userId)
            .build());
    }

    /**
     * Flushes buffered events.
     */
    public void flushEvents() throws ZentinelleException {
        if (agentId == null) {
            return;
        }

        List<Event> events;
        synchronized (eventBuffer) {
            if (eventBuffer.isEmpty()) {
                return;
            }
            events = new ArrayList<>(eventBuffer);
            eventBuffer.clear();
        }

        try {
            request("POST", "/events", Map.of(
                "agent_id", agentId,
                "events", events.stream().map(Event::toMap).toList()
            ));
            log.debug("Flushed {} events", events.size());
        } catch (ZentinelleException e) {
            // Re-queue events on failure (check against maxBufferSize to avoid overflow)
            synchronized (eventBuffer) {
                if (eventBuffer.size() + events.size() <= maxBufferSize) {
                    eventBuffer.addAll(0, events);
                } else {
                    log.warn("Failed to flush {} events and buffer is full, events dropped", events.size());
                }
            }
            throw e;
        }
    }

    private void flushEventsAsync() {
        if (!registered.get() || shutdown) return;
        try {
            flushEvents();
        } catch (Exception e) {
            log.warn("Failed to flush events: {}", e.getMessage());
        }
    }

    /**
     * Sends a heartbeat.
     */
    public HeartbeatResult heartbeat(String status, Map<String, Object> metrics) throws ZentinelleException {
        if (!registered.get() || agentId == null) {
            return null;
        }

        String heartbeatStatus = (status == null || status.isBlank()) ? "healthy" : status;
        Map<String, Object> response = request("POST", "/heartbeat", Map.of(
            "agent_id", agentId,
            "status", heartbeatStatus,
            "metrics", metrics != null ? metrics : Map.of()
        ));

        boolean configChanged = Boolean.TRUE.equals(response.get("config_changed")) ||
            Boolean.TRUE.equals(response.get("drift_detected")) ||
            Boolean.TRUE.equals(response.get("sync_required"));
        int nextHeartbeatSeconds = response.get("next_heartbeat_seconds") instanceof Number value
            ? value.intValue()
            : 60;

        return HeartbeatResult.builder()
            .acknowledged(response.get("acknowledged") instanceof Boolean value ? value : true)
            .configChanged(configChanged)
            .nextHeartbeatSeconds(nextHeartbeatSeconds)
            .build();
    }

    /**
     * Shuts down the client gracefully.
     */
    public void shutdown() {
        shutdown = true;
        scheduler.shutdown();
        try {
            scheduler.awaitTermination(5, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        try {
            flushEvents();
        } catch (Exception e) {
            log.warn("Failed to flush events during shutdown: {}", e.getMessage());
        }

        // Properly close OkHttpClient resources
        httpClient.dispatcher().executorService().shutdown();
        httpClient.connectionPool().evictAll();
        if (httpClient.cache() != null) {
            try {
                httpClient.cache().close();
            } catch (IOException e) {
                log.debug("Failed to close HTTP cache: {}", e.getMessage());
            }
        }
    }

    @Override
    public void close() {
        shutdown();
    }

    /**
     * Returns the agent ID.
     */
    public String getAgentId() {
        return agentId;
    }

    /**
     * Returns whether the agent is registered.
     */
    public boolean isRegistered() {
        return registered.get();
    }

    /**
     * Returns a string representation of the client with masked API key.
     */
    @Override
    public String toString() {
        String maskedKey = "***";
        if (apiKey.length() > 12) {
            maskedKey = apiKey.substring(0, 8) + "..." + apiKey.substring(apiKey.length() - 4);
        }
        return String.format("ZentinelleClient(agent_id=\"%s\", agent_type=\"%s\", endpoint=\"%s\", api_key=\"%s\")",
            agentId, agentType, endpoint, maskedKey);
    }

    // HTTP request handling for evaluate (with proper fail-open response)
    private Map<String, Object> requestForEvaluate(String method, String path, Map<String, Object> body)
            throws ZentinelleException {

        if (!circuitBreaker.canExecute()) {
            if (failOpen) {
                log.warn("Circuit breaker OPEN, failing open for evaluate request");
                return createFailOpenEvaluateResponse();
            }
            throw new ConnectionException("Circuit breaker is open");
        }

        try {
            return request(method, path, body, false);
        } catch (ConnectionException e) {
            if (failOpen) {
                log.warn("Request failed, failing open: {}", e.getMessage());
                return createFailOpenEvaluateResponse();
            }
            throw e;
        }
    }

    private Map<String, Object> createFailOpenEvaluateResponse() {
        return Map.of(
            "allowed", true,
            "reason", "fail_open",
            "fail_open", true,
            "warnings", List.of("Service unavailable - fail-open mode active"),
            "policies_evaluated", List.of(),
            "context", Map.of()
        );
    }

    // HTTP request handling
    private Map<String, Object> request(String method, String path, Map<String, Object> body)
            throws ZentinelleException {
        return request(method, path, body, false);
    }

    private Map<String, Object> request(String method, String path, Map<String, Object> body, boolean forRegistration)
            throws ZentinelleException {

        if (!circuitBreaker.canExecute()) {
            if (failOpen) {
                return Map.of("fail_open", true);
            }
            throw new ConnectionException("Circuit breaker is open");
        }

        String url = endpoint + API_BASE_PATH + path;
        ZentinelleException lastException = null;

        for (int attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                Request.Builder requestBuilder = new Request.Builder()
                    .url(url)
                    .header("Content-Type", "application/json")
                    .header("User-Agent", "zentinelle-java/0.1.0");

                String currentApiKey = apiKey;
                if (forRegistration && currentApiKey.startsWith("bt_")) {
                    requestBuilder.header("X-Zentinelle-Bootstrap", currentApiKey);
                } else {
                    requestBuilder.header("X-Zentinelle-Key", currentApiKey);
                }

                if (orgId != null) {
                    requestBuilder.header("X-Zentinelle-Org", orgId);
                }

                if (body != null) {
                    String json = objectMapper.writeValueAsString(body);
                    requestBuilder.method(method, RequestBody.create(json, MediaType.parse("application/json")));
                } else {
                    requestBuilder.method(method, null);
                }

                try (Response response = httpClient.newCall(requestBuilder.build()).execute()) {
                    return handleResponse(response);
                }

            } catch (RateLimitException e) {
                circuitBreaker.recordSuccess();
                throw e;
            } catch (AuthException e) {
                throw e;
            } catch (ConnectionException e) {
                lastException = e;
                circuitBreaker.recordFailure();
                if (attempt < maxRetries) {
                    sleep(backoffDelay(attempt));
                }
            } catch (IOException e) {
                lastException = new ConnectionException("Request failed: " + e.getMessage());
                circuitBreaker.recordFailure();
                if (attempt < maxRetries) {
                    sleep(backoffDelay(attempt));
                }
            }
        }

        if (failOpen) {
            return Map.of();
        }
        throw lastException;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> handleResponse(Response response) throws ZentinelleException, IOException {
        int code = response.code();
        String body = response.body() != null ? response.body().string() : "";

        switch (code) {
            case 200, 201, 202 -> {
                circuitBreaker.recordSuccess();
                return objectMapper.readValue(body, Map.class);
            }
            case 401 -> throw new AuthException("Invalid or expired API key");
            case 403 -> throw new AuthException("Access denied");
            case 429 -> {
                int retryAfter = 60;
                String retryHeader = response.header("Retry-After");
                if (retryHeader != null) {
                    try { retryAfter = Integer.parseInt(retryHeader); } catch (NumberFormatException ignored) {}
                }
                throw new RateLimitException("Rate limit exceeded", retryAfter);
            }
            default -> {
                if (code >= 500) {
                    throw new ConnectionException("Server error: " + code);
                }
                throw new ZentinelleException("Request failed: " + code + " - " + body);
            }
        }
    }

    private Duration backoffDelay(int attempt) {
        long delay = Math.min((1L << attempt) * 1000, 60000);
        return Duration.ofMillis(delay);
    }

    private void sleep(Duration duration) {
        try {
            Thread.sleep(duration.toMillis());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // Helper methods for type casting
    @SuppressWarnings("unchecked")
    private Map<String, Object> castToMap(Object obj) {
        return obj instanceof Map ? (Map<String, Object>) obj : Map.of();
    }

    @SuppressWarnings("unchecked")
    private Map<String, String> castToStringMap(Object obj) {
        if (obj instanceof Map) {
            Map<String, String> result = new HashMap<>();
            ((Map<String, Object>) obj).forEach((k, v) -> result.put(k, String.valueOf(v)));
            return result;
        }
        return Map.of();
    }

    @SuppressWarnings("unchecked")
    private List<String> castToStringList(Object obj) {
        if (!(obj instanceof List)) {
            return List.of();
        }
        List<?> list = (List<?>) obj;
        List<String> result = new ArrayList<>(list.size());
        for (Object item : list) {
            if (item instanceof String) {
                result.add((String) item);
            } else if (item != null) {
                result.add(String.valueOf(item));
            }
        }
        return result;
    }

    @SuppressWarnings("unchecked")
    private List<PolicyConfig> parsePolicies(Object obj) {
        if (!(obj instanceof List)) return List.of();
        return ((List<Map<String, Object>>) obj).stream()
            .map(m -> PolicyConfig.builder()
                .id((String) m.get("id"))
                .name((String) m.get("name"))
                .type((String) m.get("type"))
                .enforcement((String) m.get("enforcement"))
                .config(copyMap(castToMap(m.get("config"))))
                .build())
            .toList();
    }

    @SuppressWarnings("unchecked")
    private List<PolicyEvaluation> parsePolicyEvaluations(Object obj) {
        if (!(obj instanceof List)) return List.of();
        return ((List<Map<String, Object>>) obj).stream()
            .map(m -> {
                // Security: never default 'passed' to true - require explicit value
                Object passedObj = m.get("passed");
                boolean passed;
                if (passedObj instanceof Boolean) {
                    passed = (Boolean) passedObj;
                } else if (passedObj == null) {
                    // Missing 'passed' field - default to false for security
                    passed = false;
                    log.warn("Policy evaluation missing 'passed' field, defaulting to false");
                } else {
                    passed = false;
                    log.warn("Policy evaluation 'passed' field is not a boolean, defaulting to false");
                }
                return PolicyEvaluation.builder()
                    .name((String) m.get("name"))
                    .type((String) m.get("type"))
                    .passed(passed)
                    .message((String) m.get("message"))
                    .build();
            })
            .toList();
    }

    private void requireAgentId() throws ZentinelleException {
        if (agentId == null || agentId.isBlank()) {
            throw new ZentinelleException("Agent not registered. Call register() first or provide agentId.");
        }
    }

    private Map<String, Object> copyMap(Map<String, Object> source) {
        return source == null ? Map.of() : new HashMap<>(source);
    }

    private Map<String, String> copyStringMap(Map<String, String> source) {
        return source == null ? Map.of() : new HashMap<>(source);
    }

    private List<PolicyConfig> copyPolicies(List<PolicyConfig> source) {
        if (source == null || source.isEmpty()) {
            return List.of();
        }
        return source.stream()
            .map(policy -> PolicyConfig.builder()
                .id(policy.getId())
                .name(policy.getName())
                .type(policy.getType())
                .enforcement(policy.getEnforcement())
                .config(copyMap(policy.getConfig()))
                .priority(policy.getPriority())
                .build())
            .toList();
    }

    private Instant parseInstant(Object value, Instant defaultValue) {
        if (value instanceof String timestamp && !timestamp.isBlank()) {
            try {
                return Instant.parse(timestamp);
            } catch (Exception ignored) {
                return defaultValue;
            }
        }
        return defaultValue;
    }

    private static boolean isLocalEndpoint(String endpoint) {
        return endpoint.contains("localhost") || endpoint.contains("127.0.0.1");
    }

    /**
     * Builder for ZentinelleClient.
     */
    public static class Builder {
        private String apiKey;
        private String agentType;
        private String endpoint;
        private String agentId;
        private String orgId;
        private Duration timeout;
        private int maxRetries;
        private boolean failOpen;
        private int bufferSize;
        private Duration flushInterval;
        private int circuitBreakerThreshold;
        private Duration circuitBreakerTimeout;
        private Duration secretsCacheTtl;
        private Duration configCacheTtl;

        public Builder apiKey(String apiKey) { this.apiKey = apiKey; return this; }
        public Builder agentType(String agentType) { this.agentType = agentType; return this; }
        public Builder endpoint(String endpoint) { this.endpoint = endpoint; return this; }
        public Builder agentId(String agentId) { this.agentId = agentId; return this; }
        public Builder orgId(String orgId) { this.orgId = orgId; return this; }
        public Builder timeout(Duration timeout) { this.timeout = timeout; return this; }
        public Builder maxRetries(int maxRetries) { this.maxRetries = maxRetries; return this; }
        public Builder failOpen(boolean failOpen) { this.failOpen = failOpen; return this; }
        public Builder bufferSize(int bufferSize) { this.bufferSize = bufferSize; return this; }
        public Builder flushInterval(Duration flushInterval) { this.flushInterval = flushInterval; return this; }
        public Builder circuitBreakerThreshold(int threshold) { this.circuitBreakerThreshold = threshold; return this; }
        public Builder circuitBreakerTimeout(Duration timeout) { this.circuitBreakerTimeout = timeout; return this; }
        public Builder secretsCacheTtl(Duration ttl) { this.secretsCacheTtl = ttl; return this; }
        public Builder configCacheTtl(Duration ttl) { this.configCacheTtl = ttl; return this; }

        public ZentinelleClient build() {
            return new ZentinelleClient(this);
        }
    }
}
