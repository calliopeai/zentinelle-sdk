# Zentinelle .NET SDK

[![NuGet](https://img.shields.io/nuget/v/Zentinelle)](https://www.nuget.org/packages/Zentinelle)
[![.NET](https://img.shields.io/badge/.NET-6.0%2B-blue)](https://dotnet.microsoft.com/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Enterprise-grade AI agent governance for .NET applications. Control, monitor, and secure your AI agents with comprehensive policy management.

## Installation

### NuGet Package Manager

```bash
dotnet add package Zentinelle
```

### Package Manager Console

```powershell
Install-Package Zentinelle
```

## Quick Start

```csharp
using Zentinelle;
using Zentinelle.Models;

// Initialize client
var client = new ZentinelleClient(new ZentinelleOptions
{
    ApiKey = "your-api-key",
    AgentId = "your-agent-id"
});

// Register agent session
var registration = await client.RegisterAsync(new RegisterOptions
{
    UserId = "user-123",
    SessionId = "session-456"
});
Console.WriteLine($"Registered: {registration.SessionId}");

// Evaluate policy before action
var result = await client.EvaluateAsync("tool_call", new EvaluateOptions
{
    Context = new Dictionary<string, object>
    {
        ["tool"] = "web_search",
        ["query"] = "company financials"
    }
});

if (result.Allowed)
{
    // Execute action
    Console.WriteLine("Action allowed");

    // Report usage
    client.Emit(Event.ToolCall("web_search", success: true));
}
else
{
    Console.WriteLine($"Action blocked: {result.Reason}");
}

// Clean shutdown
await client.DisposeAsync();
```

## Features

### Policy Evaluation

Check policies before executing actions:

```csharp
// Simple evaluation
var result = await client.EvaluateAsync("model_request");

// Evaluation with context
var result = await client.EvaluateAsync("tool_call", new EvaluateOptions
{
    Context = new Dictionary<string, object>
    {
        ["tool"] = "database_query",
        ["tables"] = new[] { "users", "orders" }
    },
    UserId = "user-123"
});

// Handle policy decisions
if (result.Allowed)
{
    await ExecuteActionAsync();
}
else if (result.RequiresApproval)
{
    await RequestApprovalAsync(result.ApprovalWorkflowId);
}
else
{
    HandleBlocked(result.Reason);
}
```

### Event Tracking

Track all agent activities:

```csharp
// Track tool call
client.Emit(new Event
{
    Category = EventCategory.ToolCall,
    Action = "web_search",
    Success = true,
    Metadata = new Dictionary<string, object>
    {
        ["query"] = "weather forecast",
        ["results_count"] = 10
    }
});

// Track model usage
client.Emit(Event.ModelRequest("gpt-4", new ModelUsage
{
    Model = "gpt-4",
    InputTokens = 150,
    OutputTokens = 500,
    Cost = 0.025m
}));

// Track errors
client.Emit(Event.Failed(EventCategory.Error, "api_call", "Connection timeout"));
```

### Configuration & Secrets

Access runtime configuration:

```csharp
// Get full configuration
var config = await client.GetConfigAsync();
Console.WriteLine($"Rate limit: {config.RateLimits?.RequestsPerMinute}");
Console.WriteLine($"Allowed models: {string.Join(", ", config.AllowedModels ?? new List<string>())}");

// Get secrets (API keys, etc.)
var secrets = await client.GetSecretsAsync();
var openaiKey = secrets["OPENAI_API_KEY"];
```

### Session Management

Manage agent sessions:

```csharp
// Register with full options
var result = await client.RegisterAsync(new RegisterOptions
{
    UserId = "user-123",
    SessionId = "session-456",
    Metadata = new Dictionary<string, object>
    {
        ["client_version"] = "2.0.0",
        ["environment"] = "production"
    }
});

// Access session info
var sessionId = result.SessionId;
var config = result.Config;
```

## Advanced Configuration

### Full Options

```csharp
var client = new ZentinelleClient(new ZentinelleOptions
{
    ApiKey = "your-api-key",
    AgentId = "your-agent-id",
    BaseUrl = "https://custom.zentinelle.ai",      // Custom endpoint
    Timeout = TimeSpan.FromSeconds(30),             // Request timeout
    MaxRetries = 3,                                 // Retry attempts
    FailOpen = true,                                // Allow on errors
    CircuitBreakerThreshold = 5,                    // Failures before open
    CircuitBreakerRecovery = TimeSpan.FromMinutes(1), // Recovery time
    HeartbeatInterval = TimeSpan.FromSeconds(30),   // Heartbeat frequency
    FlushInterval = TimeSpan.FromSeconds(5),        // Event flush interval
    MaxBatchSize = 100                              // Max events per batch
});
```

### From Environment Variables

```csharp
// Uses ZENTINELLE_API_KEY and ZENTINELLE_AGENT_ID
var client = ZentinelleClient.FromEnvironment();
```

### Dependency Injection

```csharp
// In Startup.cs or Program.cs
services.AddSingleton<ZentinelleClient>(sp =>
{
    var logger = sp.GetService<ILogger<ZentinelleClient>>();
    return new ZentinelleClient(new ZentinelleOptions
    {
        ApiKey = configuration["Zentinelle:ApiKey"]!,
        AgentId = configuration["Zentinelle:AgentId"]!
    }, logger);
});

// In your service
public class MyAgentService
{
    private readonly ZentinelleClient _client;

    public MyAgentService(ZentinelleClient client)
    {
        _client = client;
    }

    public async Task<string> ProcessRequestAsync(string input)
    {
        var result = await _client.EvaluateAsync("model_request");
        if (!result.Allowed)
        {
            throw new PolicyViolationException("Blocked", result);
        }
        // Process...
    }
}
```

## Error Handling

```csharp
using Zentinelle.Exceptions;

try
{
    var result = await client.EvaluateAsync("action");
}
catch (AuthenticationException ex)
{
    // Invalid API key
    Console.Error.WriteLine($"Authentication failed: {ex.Message}");
}
catch (RateLimitException ex)
{
    // Rate limited
    Console.Error.WriteLine($"Rate limited. Retry after: {ex.RetryAfterSeconds}s");
    await Task.Delay(TimeSpan.FromSeconds(ex.RetryAfterSeconds));
}
catch (PolicyViolationException ex)
{
    // Policy blocked action
    var result = ex.Result;
    Console.Error.WriteLine($"Blocked: {result.Reason}");
}
catch (ConnectionException ex)
{
    // Network error
    Console.Error.WriteLine($"Connection failed: {ex.Message}");
}
catch (ZentinelleException ex)
{
    // Other errors
    Console.Error.WriteLine($"Error: {ex.Message}");
}
```

## Semantic Kernel Integration

```csharp
using Microsoft.SemanticKernel;

public class GovernedKernel
{
    private readonly Kernel _kernel;
    private readonly ZentinelleClient _client;

    public GovernedKernel(Kernel kernel, ZentinelleClient client)
    {
        _kernel = kernel;
        _client = client;
    }

    public async Task<string> InvokeAsync(string prompt)
    {
        // Check policy before invocation
        var result = await _client.EvaluateAsync("model_request", new EvaluateOptions
        {
            Context = new Dictionary<string, object>
            {
                ["prompt_length"] = prompt.Length
            }
        });

        if (!result.Allowed)
        {
            throw new PolicyViolationException("Request blocked", result);
        }

        var stopwatch = Stopwatch.StartNew();
        var response = await _kernel.InvokePromptAsync(prompt);
        stopwatch.Stop();

        // Track usage
        _client.Emit(new Event
        {
            Category = EventCategory.ModelRequest,
            Action = "invoke_prompt",
            Success = true,
            DurationMs = stopwatch.ElapsedMilliseconds
        });

        return response.GetValue<string>() ?? string.Empty;
    }
}
```

## ASP.NET Core Middleware

```csharp
public class ZentinelleMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ZentinelleClient _client;

    public ZentinelleMiddleware(RequestDelegate next, ZentinelleClient client)
    {
        _next = next;
        _client = client;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        var result = await _client.EvaluateAsync("api_request", new EvaluateOptions
        {
            Context = new Dictionary<string, object>
            {
                ["path"] = context.Request.Path.Value ?? "",
                ["method"] = context.Request.Method
            },
            UserId = context.User.Identity?.Name
        });

        if (!result.Allowed)
        {
            context.Response.StatusCode = 403;
            await context.Response.WriteAsJsonAsync(new
            {
                error = "Policy violation",
                reason = result.Reason
            });
            return;
        }

        await _next(context);
    }
}

// Register middleware
app.UseMiddleware<ZentinelleMiddleware>();
```

## Thread Safety

The `ZentinelleClient` is fully thread-safe. A single instance can be shared:

```csharp
// Create once as singleton
private static readonly ZentinelleClient Client = new(new ZentinelleOptions
{
    ApiKey = Environment.GetEnvironmentVariable("ZENTINELLE_API_KEY")!,
    AgentId = Environment.GetEnvironmentVariable("ZENTINELLE_AGENT_ID")!
});

// Safe to call from multiple threads
await Parallel.ForEachAsync(
    Enumerable.Range(0, 100),
    async (i, ct) =>
    {
        var result = await Client.EvaluateAsync("action");
        // ...
    });
```

## Best Practices

1. **Reuse Client Instance**: Create one client and reuse it via DI
2. **Use Async Methods**: Prefer `EvaluateAsync` over `Evaluate`
3. **Handle Errors Gracefully**: Use try-catch with specific exception types
4. **Configure Fail-Open**: Set `FailOpen = true` for non-critical paths
5. **Dispose Properly**: Use `await using` or call `DisposeAsync()`
6. **Use Cancellation Tokens**: Pass tokens to async methods for proper cancellation

## Requirements

- .NET 6.0, 7.0, or 8.0
- Dependencies (auto-resolved via NuGet):
  - Microsoft.Extensions.Logging.Abstractions
  - System.Text.Json
  - Polly

## License

Apache 2.0

## Support

- Documentation: [https://docs.zentinelle.ai](https://docs.zentinelle.ai)
- Issues: [https://github.com/zentinelle/zentinelle-dotnet/issues](https://github.com/zentinelle/zentinelle-dotnet/issues)
- Email: support@zentinelle.ai
