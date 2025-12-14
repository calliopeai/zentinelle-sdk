# Zentinelle Java SDK

[![Maven Central](https://img.shields.io/maven-central/v/ai.zentinelle/zentinelle-sdk)](https://search.maven.org/artifact/ai.zentinelle/zentinelle-sdk)
[![Java](https://img.shields.io/badge/Java-11%2B-blue)](https://www.oracle.com/java/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Enterprise-grade AI agent governance for Java applications. Control, monitor, and secure your AI agents with comprehensive policy management.

## Installation

### Maven

```xml
<dependency>
    <groupId>ai.zentinelle</groupId>
    <artifactId>zentinelle-sdk</artifactId>
    <version>0.1.0</version>
</dependency>
```

### Gradle

```groovy
implementation 'ai.zentinelle:zentinelle-sdk:0.1.0'
```

### Gradle (Kotlin DSL)

```kotlin
implementation("ai.zentinelle:zentinelle-sdk:0.1.0")
```

## Quick Start

```java
import ai.zentinelle.ZentinelleClient;
import ai.zentinelle.model.*;

public class QuickStart {
    public static void main(String[] args) {
        // Initialize client
        ZentinelleClient client = ZentinelleClient.builder()
            .apiKey("your-api-key")
            .agentId("your-agent-id")
            .build();

        try {
            // Register agent
            RegisterResult registration = client.register(
                RegisterOptions.builder()
                    .capabilities(List.of("chat", "tools"))
                    .build()
            );
            System.out.println("Registered agent: " + registration.getAgentId());

            // Evaluate policy before action
            EvaluateResult result = client.evaluate(
                "tool_call",
                EvaluateOptions.builder()
                    .context(Map.of(
                        "tool", "web_search",
                        "query", "company financials"
                    ))
                    .build()
            );

            if (result.isAllowed()) {
                // Execute action
                System.out.println("Action allowed");

                // Report usage
                client.emit(
                    "tool_call",
                    Map.of("tool", "web_search", "success", true),
                    EmitOptions.builder()
                        .category(EventCategory.AUDIT)
                        .build()
                );
            } else {
                System.out.println("Action blocked: " + result.getReason());
            }

        } finally {
            // Clean shutdown
            client.close();
        }
    }
}
```

## Features

### Policy Evaluation

Check policies before executing actions:

```java
// Simple evaluation
EvaluateResult result = client.evaluate("model_request");

// Evaluation with context
EvaluateResult result = client.evaluate(
    "tool_call",
    EvaluateOptions.builder()
        .context(Map.of(
            "tool", "database_query",
            "tables", List.of("users", "orders")
        ))
        .userId("user-123")
        .build()
);

// Handle policy decisions
if (result.isAllowed()) {
    executeAction();
} else if (result.requiresHumanApproval()) {
    requestApproval(result.getApprovalWorkflowId());
} else {
    handleBlocked(result.getReason());
}
```

### Event Tracking

Track all agent activities:

```java
// Track tool call
client.emit(
    "tool_call",
    Map.of(
        "tool", "web_search",
        "query", "weather forecast",
        "results_count", 10
    ),
    EmitOptions.builder()
        .category(EventCategory.AUDIT)
        .userId("user-123")
        .build()
);

// Track model usage
client.trackUsage(ModelUsage.builder()
    .provider("openai")
    .model("gpt-4")
    .inputTokens(150)
    .outputTokens(500)
    .estimatedCost(0.025)
    .build()
);

// Track errors
client.emit(
    "api_error",
    Map.of(
        "error", "Connection timeout",
        "endpoint", "/api/data"
    ),
    EmitOptions.builder()
        .category(EventCategory.ALERT)
        .build()
);
```

### Secrets

Access runtime secrets:

```java
// Get secrets (API keys, etc.)
Map<String, String> secrets = client.getSecrets();
String openaiKey = secrets.get("OPENAI_API_KEY");
```

### Agent Registration

Register agents with capabilities and metadata:

```java
// Register with full options
RegisterResult result = client.register(
    RegisterOptions.builder()
        .capabilities(List.of("chat", "tools", "rag"))
        .name("my-agent")
        .metadata(Map.of(
            "client_version", "2.0.0",
            "environment", "production"
        ))
        .build()
);

// Access registration info
String agentId = result.getAgentId();
Map<String, Object> config = result.getConfig();
List<PolicyConfig> policies = result.getPolicies();
```

## Advanced Configuration

### Builder Options

```java
ZentinelleClient client = ZentinelleClient.builder()
    .apiKey("your-api-key")
    .agentId("your-agent-id")
    .baseUrl("https://custom.zentinelle.ai")  // Custom endpoint
    .timeout(Duration.ofSeconds(30))           // Request timeout
    .maxRetries(3)                             // Retry attempts
    .failOpen(true)                            // Allow on errors
    .circuitBreakerThreshold(5)                // Failures before open
    .circuitBreakerRecovery(Duration.ofMinutes(1))  // Recovery time
    .heartbeatInterval(Duration.ofSeconds(30)) // Heartbeat frequency
    .flushInterval(Duration.ofSeconds(5))      // Event flush interval
    .maxBatchSize(100)                         // Max events per batch
    .build();
```

### Background Event Flushing

Events are automatically buffered and flushed in the background:

```java
// Events are buffered and flushed automatically every 5 seconds (configurable)
client.emit("tool_call", Map.of("tool", "search"), EmitOptions.builder().build());

// Or flush manually when needed
client.flushEvents();
```

The client uses a background thread for event flushing, so `emit()` calls are non-blocking.

### Custom HTTP Client

Use your own OkHttpClient:

```java
OkHttpClient customClient = new OkHttpClient.Builder()
    .connectTimeout(Duration.ofSeconds(10))
    .readTimeout(Duration.ofSeconds(30))
    .addInterceptor(new LoggingInterceptor())
    .build();

ZentinelleClient client = ZentinelleClient.builder()
    .apiKey("your-api-key")
    .agentId("your-agent-id")
    .httpClient(customClient)
    .build();
```

## Error Handling

```java
import ai.zentinelle.exception.*;

try {
    EvaluateResult result = client.evaluate("action");
} catch (AuthException e) {
    // Invalid API key
    System.err.println("Authentication failed: " + e.getMessage());
} catch (RateLimitException e) {
    // Rate limited
    System.err.println("Rate limited. Retry after: " + e.getRetryAfter() + "s");
    Thread.sleep(e.getRetryAfter() * 1000);
} catch (PolicyViolationException e) {
    // Policy blocked action
    EvaluateResult result = e.getResult();
    System.err.println("Blocked: " + result.getReason());
} catch (ConnectionException e) {
    // Network error
    System.err.println("Connection failed: " + e.getMessage());
} catch (ZentinelleException e) {
    // Other errors
    System.err.println("Error: " + e.getMessage());
}
```

## Spring Boot Integration

### Configuration

```java
@Configuration
public class ZentinelleConfig {

    @Value("${zentinelle.api-key}")
    private String apiKey;

    @Value("${zentinelle.agent-id}")
    private String agentId;

    @Bean
    public ZentinelleClient zentinelleClient() {
        return ZentinelleClient.builder()
            .apiKey(apiKey)
            .agentId(agentId)
            .build();
    }
}
```

### AOP Aspect for Governance

```java
@Aspect
@Component
public class GovernanceAspect {

    @Autowired
    private ZentinelleClient client;

    @Around("@annotation(Governed)")
    public Object checkPolicy(ProceedingJoinPoint joinPoint) throws Throwable {
        Governed annotation = getAnnotation(joinPoint);

        EvaluateResult result = client.evaluate(
            annotation.action(),
            EvaluateOptions.builder()
                .context(extractContext(joinPoint))
                .build()
        );

        if (!result.isAllowed()) {
            throw new PolicyViolationException("Blocked: " + result.getReason(), result);
        }

        try {
            Object response = joinPoint.proceed();
            client.emit(Event.success(annotation.action()));
            return response;
        } catch (Exception e) {
            client.emit(Event.failure(annotation.action(), e.getMessage()));
            throw e;
        }
    }
}

// Usage
@Governed(action = "database_query")
public List<User> queryUsers(String filter) {
    return userRepository.findByFilter(filter);
}
```

## LangChain4j Integration

```java
import dev.langchain4j.model.chat.ChatLanguageModel;

public class GovernedChatModel implements ChatLanguageModel {

    private final ChatLanguageModel delegate;
    private final ZentinelleClient client;

    public GovernedChatModel(ChatLanguageModel delegate, ZentinelleClient client) {
        this.delegate = delegate;
        this.client = client;
    }

    @Override
    public String generate(String prompt) {
        EvaluateResult result = client.evaluate(
            "model_request",
            EvaluateOptions.builder()
                .context(Map.of("prompt_length", prompt.length()))
                .build()
        );

        if (!result.isAllowed()) {
            throw new PolicyViolationException("Request blocked", result);
        }

        long startTime = System.currentTimeMillis();
        String response = delegate.generate(prompt);
        long duration = System.currentTimeMillis() - startTime;

        client.emit(
            "model_request",
            Map.of(
                "action", "generate",
                "success", true,
                "duration_ms", duration
            ),
            EmitOptions.builder()
                .category(EventCategory.TELEMETRY)
                .build()
        );

        return response;
    }
}
```

## Thread Safety

The `ZentinelleClient` is fully thread-safe. A single instance can be shared across multiple threads:

```java
// Create once, use everywhere
private static final ZentinelleClient CLIENT = ZentinelleClient.builder()
    .apiKey(System.getenv("ZENTINELLE_API_KEY"))
    .agentId(System.getenv("ZENTINELLE_AGENT_ID"))
    .build();

// Safe to call from multiple threads
ExecutorService executor = Executors.newFixedThreadPool(10);
for (int i = 0; i < 100; i++) {
    executor.submit(() -> {
        EvaluateResult result = CLIENT.evaluate("action");
        // ...
    });
}
```

## Best Practices

1. **Reuse Client Instance**: Create one client and reuse it across your application
2. **Handle Errors Gracefully**: Use try-catch and consider fail-open for non-critical paths
3. **Use Async for Events**: Event emission is non-blocking by default
4. **Configure Timeouts**: Set appropriate timeouts for your use case
5. **Monitor Circuit Breaker**: Log when circuit breaker opens/closes
6. **Shutdown Properly**: Always call `close()` to flush pending events

## Requirements

- Java 11 or higher
- Dependencies:
  - OkHttp 4.x
  - Jackson 2.x

## License

Apache 2.0

## Support

- Documentation: [https://docs.zentinelle.ai](https://docs.zentinelle.ai)
- Issues: [https://github.com/zentinelle/zentinelle-java/issues](https://github.com/zentinelle/zentinelle-java/issues)
- Email: support@zentinelle.ai
