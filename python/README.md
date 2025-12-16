# Zentinelle Python SDK

Python client library for AI agent governance and runtime control.

## Installation

```bash
pip install zentinelle
```

## Quick Start

```python
from zentinelle import ZentinelleClient

client = ZentinelleClient(
    api_key="sk_agent_...",
    agent_type="langchain",
)

# Register on startup
result = client.register(capabilities=["chat", "tools"])

# Evaluate policies before actions
eval_result = client.evaluate("tool_call", user_id="user123", context={"tool": "web_search"})
if not eval_result.allowed:
    raise PermissionError(eval_result.reason)

# Track model usage
client.emit_model_request("openai", "gpt-4", input_tokens=100, output_tokens=50, user_id="user123")

# Graceful shutdown
client.shutdown()
```

## Features

- **Policy Evaluation** - Check permissions before actions
- **Configuration Management** - Centralized config with caching
- **Secrets Management** - Secure credential delivery
- **Event Telemetry** - Buffered, async event emission
- **Heartbeats** - Background health monitoring
- **Resilience** - Retry logic, circuit breaker, fail-open mode

## Context Manager

```python
from zentinelle import ZentinelleClient

with ZentinelleClient(api_key="sk_agent_...", agent_type="test") as client:
    client.register()
    result = client.evaluate("action", user_id="user123")
# Automatically calls shutdown() on exit
```

## Error Handling

```python
from zentinelle import (
    ZentinelleClient,
    ZentinelleError,
    ZentinelleConnectionError,
    ZentinelleAuthError,
    ZentinelleRateLimitError,
)

try:
    result = client.evaluate("spawn", user_id="user123")
except ZentinelleRateLimitError as e:
    print(f"Rate limited, retry after {e.retry_after}s")
except ZentinelleAuthError:
    print("Invalid API key")
except ZentinelleConnectionError:
    print("Cannot reach Zentinelle service")
```

## API Reference

### ZentinelleClient

```python
client = ZentinelleClient(
    api_key="sk_agent_...",           # Required
    agent_type="langchain",            # Required
    endpoint="https://api.zentinelle.ai",  # Optional
    agent_id=None,                     # Optional, assigned on register()
    org_id=None,                       # Optional
    timeout=30,                        # Request timeout in seconds
    fail_open=True,                    # Return allowed=True on service failure
    auto_heartbeat=True,               # Send heartbeats automatically
    heartbeat_interval=60,             # Seconds between heartbeats
    event_buffer_size=100,             # Events to buffer before flush
    event_flush_interval=10,           # Seconds between flushes
    config_cache_ttl=300,              # Config cache TTL in seconds
    secrets_cache_ttl=60,              # Secrets cache TTL in seconds
)
```

### Methods

#### `register(capabilities=None, metadata=None, name=None)`
Register agent with Zentinelle. Returns `RegisterResult`.

#### `get_config(force_refresh=False)`
Get configuration and policies. Returns `ConfigResult`.

#### `get_secrets(force_refresh=False)`
Get secrets. Returns `Dict[str, str]`.

#### `get_secret(key, default=None)`
Get a single secret value.

#### `evaluate(action, user_id=None, context=None)`
Evaluate policies for an action. Returns `EvaluateResult`.

#### `can_use_model(model, user_id=None)`
Check if model usage is allowed. Returns `EvaluateResult`.

#### `can_call_tool(tool_name, user_id=None, context=None)`
Check if tool call is allowed. Returns `EvaluateResult`.

#### `emit(event_type, payload=None, category='telemetry', user_id=None)`
Emit an event (buffered, async).

#### `emit_model_request(provider, model, input_tokens, output_tokens, user_id=None, duration_ms=None)`
Emit a model request event.

#### `emit_tool_call(tool_name, user_id=None, success=True, duration_ms=None, error=None)`
Emit a tool call event.

#### `track_usage(model_usage)`
Track model usage from a `ModelUsage` object.

#### `heartbeat(status='healthy', metrics=None)`
Send a heartbeat manually. Returns `HeartbeatResult`.

#### `flush_events()`
Manually flush buffered events. Returns `EventsResult`.

#### `shutdown(timeout=5.0)`
Graceful shutdown: flush events and stop background threads.

### Types

```python
from zentinelle import (
    EvaluateResult,    # Policy evaluation result
    PolicyConfig,      # Policy configuration
    RegisterResult,    # Registration result
    ConfigResult,      # Config fetch result
    EventsResult,      # Event submission result
    HeartbeatResult,   # Heartbeat result
    ModelUsage,        # Model usage tracking
)
```

#### ModelUsage Helpers

```python
from zentinelle import ModelUsage

# From OpenAI response
usage = ModelUsage.from_openai(openai_response)
client.track_usage(usage)

# From Anthropic response
usage = ModelUsage.from_anthropic(anthropic_response)
client.track_usage(usage)
```

## Configuration

### Retry Configuration

```python
from zentinelle import RetryConfig, ZentinelleClient

client = ZentinelleClient(
    api_key="sk_agent_...",
    agent_type="test",
    retry_config=RetryConfig(
        max_retries=3,
        base_delay=1.0,
        max_delay=60.0,
        exponential_base=2.0,
        jitter=True,
    ),
)
```

### Fail-Open Mode

When `fail_open=True` (default), the client returns `allowed=True` if the Zentinelle service is unavailable. Check `result.fail_open` to detect this:

```python
result = client.evaluate("action", user_id="user123")
if result.fail_open:
    logger.warning("Zentinelle unavailable, proceeding with fail-open")
```

## Thread Safety

The client is thread-safe. All caches and buffers are protected by locks. Background threads handle heartbeats and event flushing.

## License

MIT License - see LICENSE file.
