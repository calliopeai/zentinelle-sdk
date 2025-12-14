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

    private final String apiKey;
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

    private String agentId;
    private final AtomicBoolean registered = new AtomicBoolean(false);
    private final List<Event> eventBuffer = Collections.synchronizedList(new ArrayList<>());
    private final int maxBufferSize; // Maximum buffer size to prevent memory leaks
    private final ScheduledExecutorService scheduler;
    private volatile boolean shutdown = false;

    private ZentinelleClient(Builder builder) {
        this.apiKey = Objects.requireNonNull(builder.apiKey, "apiKey is required");
        if (this.apiKey.length() < 10) {
            throw new IllegalArgumentException("apiKey format is invalid");
        }
        this.agentType = Objects.requireNonNull(builder.agentType, "agentType is required");
        this.endpoint = builder.endpoint != null ? builder.endpoint : DEFAULT_ENDPOINT;
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
        Map<String, Object> body = new HashMap<>();
        body.put("agent_id", agentId);
        body.put("agent_type", agentType);
        body.put("capabilities", options.getCapabilities());
        body.put("metadata", options.getMetadata());
        body.put("name", options.getName());

        Map<String, Object> response = request("POST", "/agents/register", body);

        this.agentId = (String) response.get("agent_id");
        this.registered.set(true);

        log.info("Registered agent: {}", agentId);

        return RegisterResult.builder()
            .agentId(agentId)
            .apiKey((String) response.get("api_key"))
            .config(castToMap(response.get("config")))
            .policies(parsePolicies(response.get("policies")))
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
        Map<String, Object> body = new HashMap<>();
        body.put("agent_id", agentId);
        body.put("action", action);
        body.put("user_id", options.getUserId());
        body.put("context", options.getContext());

        Map<String, Object> response = requestForEvaluate("POST", "/evaluate", body);

        // Check for fail-open response
        boolean isFailOpen = Boolean.TRUE.equals(response.get("fail_open"));

        // Critical: validate that 'allowed' field is present (unless fail-open)
        // Never default to true - this would bypass security
        Object allowedObj = response.get("allowed");
        if (!isFailOpen && allowedObj == null) {
            throw new ZentinelleException("Invalid response: missing required 'allowed' field");
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
     * Retrieves secrets for the agent.
     */
    public Map<String, String> getSecrets() throws ZentinelleException {
        Map<String, Object> response = request("GET", "/agents/" + agentId + "/secrets", null);
        return castToStringMap(response.get("secrets"));
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

        boolean shouldFlush;
        synchronized (eventBuffer) {
            // Enforce max buffer size to prevent memory leaks
            if (eventBuffer.size() >= maxBufferSize) {
                int dropped = eventBuffer.size() - maxBufferSize + 1;
                for (int i = 0; i < dropped; i++) {
                    eventBuffer.remove(0);
                }
                log.warn("Event buffer at max capacity, dropped {} oldest events", dropped);
            }
            eventBuffer.add(event);
            shouldFlush = eventBuffer.size() >= bufferSize;
        }

        if (shouldFlush) {
            flushEventsAsync();
        }
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
            // Re-queue events on failure
            synchronized (eventBuffer) {
                if (eventBuffer.size() < bufferSize * 2) {
                    eventBuffer.addAll(0, events);
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
    public void heartbeat(String status, Map<String, Object> metrics) throws ZentinelleException {
        if (!registered.get() || agentId == null) return;

        request("POST", "/heartbeat", Map.of(
            "agent_id", agentId,
            "status", status,
            "metrics", metrics != null ? metrics : Map.of()
        ));
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
            return request(method, path, body);
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

        if (!circuitBreaker.canExecute()) {
            if (failOpen) {
                return Map.of("fail_open", true);
            }
            throw new ConnectionException("Circuit breaker is open");
        }

        String url = endpoint + "/api/v1" + path;
        ZentinelleException lastException = null;

        for (int attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                Request.Builder requestBuilder = new Request.Builder()
                    .url(url)
                    .header("Content-Type", "application/json")
                    .header("User-Agent", "zentinelle-java/0.1.0")
                    .header("X-Zentinelle-Key", apiKey);

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
            case 200, 201 -> {
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
        return obj instanceof List ? (List<String>) obj : List.of();
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
                .config(castToMap(m.get("config")))
                .build())
            .toList();
    }

    @SuppressWarnings("unchecked")
    private List<PolicyEvaluation> parsePolicyEvaluations(Object obj) {
        if (!(obj instanceof List)) return List.of();
        return ((List<Map<String, Object>>) obj).stream()
            .map(m -> PolicyEvaluation.builder()
                .name((String) m.get("name"))
                .type((String) m.get("type"))
                .passed((Boolean) m.getOrDefault("passed", true))
                .message((String) m.get("message"))
                .build())
            .toList();
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

        public ZentinelleClient build() {
            return new ZentinelleClient(this);
        }
    }
}
