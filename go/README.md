# Zentinelle Go SDK

[![Go Reference](https://pkg.go.dev/badge/github.com/calliopeai/zentinelle-go.svg)](https://pkg.go.dev/github.com/calliopeai/zentinelle-go)
[![Go Report Card](https://goreportcard.com/badge/github.com/calliopeai/zentinelle-go)](https://goreportcard.com/report/github.com/calliopeai/zentinelle-go)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

Go client for [Zentinelle](https://zentinelle.ai) - AI Agent Governance & Runtime Control.

## Installation

```bash
go get github.com/calliopeai/zentinelle-go
```

## Quick Start

```go
package main

import (
    "context"
    "log"

    "github.com/calliopeai/zentinelle-go/zentinelle"
)

func main() {
    // Create client
    client, err := zentinelle.NewClient(zentinelle.Config{
        APIKey:    "sk_agent_...",
        AgentType: "go-agent",
    })
    if err != nil {
        log.Fatal(err)
    }
    defer client.Shutdown()

    ctx := context.Background()

    // Register on startup
    result, err := client.Register(ctx, zentinelle.RegisterOptions{
        Capabilities: []string{"chat", "tools"},
        Metadata: map[string]interface{}{
            "version": "1.0.0",
        },
    })
    if err != nil {
        log.Fatal(err)
    }
    log.Printf("Registered agent: %s", result.AgentID)

    // Evaluate policies before actions
    eval, err := client.Evaluate(ctx, "tool_call", zentinelle.EvaluateOptions{
        UserID:  "user123",
        Context: map[string]interface{}{"tool": "web_search"},
    })
    if err != nil {
        log.Fatal(err)
    }

    if !eval.Allowed {
        log.Fatalf("Action blocked: %s", eval.Reason)
    }

    // Track model usage
    client.TrackUsage(zentinelle.ModelUsage{
        Provider:     "openai",
        Model:        "gpt-4o",
        InputTokens:  100,
        OutputTokens: 50,
    })

    // Emit events (buffered, async)
    client.Emit("task_completed", map[string]interface{}{
        "task_id": "123",
        "success": true,
    }, zentinelle.EmitOptions{Category: "audit"})
}
```

## Features

### Policy Evaluation

Check policies before performing actions:

```go
// Generic evaluation
result, err := client.Evaluate(ctx, "custom_action", zentinelle.EvaluateOptions{
    UserID:  "user123",
    Context: map[string]interface{}{
        "key": "value",
    },
})

// Convenience methods
canUseModel, _ := client.CanUseModel(ctx, "gpt-4o", "openai")
canCallTool, _ := client.CanCallTool(ctx, "web_search", "user123")
```

### Secrets Management

Securely retrieve secrets:

```go
secrets, err := client.GetSecrets(ctx)
if err != nil {
    log.Fatal(err)
}

openaiKey := secrets["OPENAI_API_KEY"]
```

### Event Telemetry

Events are buffered and sent in batches:

```go
// Emit custom events
client.Emit("agent_action", payload, zentinelle.EmitOptions{
    Category: "audit",
    UserID:   "user123",
})

// Convenience methods
client.EmitToolCall("web_search", "user123", 150) // 150ms duration

// Manual flush if needed
client.FlushEvents(ctx)
```

### Usage Tracking

Track model usage for cost policies:

```go
client.TrackUsage(zentinelle.ModelUsage{
    Provider:      "openai",
    Model:         "gpt-4o",
    InputTokens:   1000,
    OutputTokens:  500,
    EstimatedCost: 0.05,
})
```

### Resilience

Built-in retry logic and circuit breaker:

```go
client, _ := zentinelle.NewClient(zentinelle.Config{
    APIKey:    "sk_agent_...",
    AgentType: "go-agent",

    // Retry configuration
    MaxRetries: 3,
    Timeout:    30 * time.Second,

    // Circuit breaker
    CircuitBreakerThreshold: 5,
    CircuitBreakerTimeout:   30 * time.Second,

    // Fail-open mode (allow actions if Zentinelle unreachable)
    FailOpen: true,
})
```

## Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `APIKey` | string | required | Your Zentinelle API key |
| `AgentType` | string | required | Agent type identifier |
| `Endpoint` | string | `https://api.zentinelle.ai` | API endpoint |
| `Timeout` | Duration | 30s | HTTP request timeout |
| `MaxRetries` | int | 3 | Maximum retry attempts |
| `FailOpen` | bool | false | Allow actions if Zentinelle unreachable |
| `BufferSize` | int | 100 | Event buffer size |
| `FlushInterval` | Duration | 5s | Event flush interval |

## Error Handling

```go
result, err := client.Evaluate(ctx, "action", opts)

switch e := err.(type) {
case *zentinelle.AuthError:
    log.Fatal("Invalid API key")
case *zentinelle.RateLimitError:
    log.Printf("Rate limited, retry after %ds", e.RetryAfter)
case *zentinelle.ConnectionError:
    log.Printf("Connection failed: %s", e.Message)
default:
    if err != nil {
        log.Fatal(err)
    }
}
```

## License

Apache-2.0
