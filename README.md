# Sentinel SDK

Python SDK for integrating AI agents with the Sentinel policy engine.

Sentinel is an agent endpoint management platform that provides:
- **Policy Enforcement** - Evaluate policies before critical actions
- **Configuration Management** - Centralized config distribution
- **Secrets Management** - Secure credential delivery
- **Event Telemetry** - Usage tracking and audit logging
- **Content Scanning** - Compliance and security monitoring

## Installation

```bash
pip install sentinel-sdk
```

## Quick Start

```python
from sentinel_sdk import SentinelClient

# Initialize the client
client = SentinelClient(
    endpoint="https://sentinel.example.com",
    api_key="sk_agent_...",
    agent_type="jupyterhub",
)

# Register on startup
result = client.register(
    capabilities=["lab", "chat"],
    metadata={"version": "1.0.0"}
)

# Get secrets (cached)
secrets = client.get_secrets()
openai_key = secrets.get("OPENAI_API_KEY")

# Evaluate policies before critical actions
result = client.evaluate(
    action="spawn",
    user_id="user123",
    context={"service": "lab", "instance_size": "large"}
)

if not result.allowed:
    raise PermissionError(result.reason)

# Emit events (buffered, async)
client.emit("spawn", {"user_id": "user123", "service": "lab"})
```

## Features

### Automatic Retries with Exponential Backoff

The SDK automatically retries failed requests with exponential backoff and jitter:

```python
from sentinel_sdk import SentinelClient, RetryConfig

client = SentinelClient(
    endpoint="https://sentinel.example.com",
    api_key="sk_agent_...",
    agent_type="custom",
    retry_config=RetryConfig(
        max_retries=3,
        base_delay=1.0,
        max_delay=60.0,
        jitter=True,
    ),
)
```

### Circuit Breaker

The SDK includes a circuit breaker to fail fast when the service is unavailable:

```python
client = SentinelClient(
    endpoint="https://sentinel.example.com",
    api_key="sk_agent_...",
    agent_type="custom",
    circuit_breaker_threshold=5,  # Open after 5 failures
    circuit_breaker_recovery=30.0,  # Test recovery after 30s
)
```

### Error Handling

```python
from sentinel_sdk import (
    SentinelClient,
    SentinelError,
    SentinelConnectionError,
    SentinelAuthError,
    SentinelRateLimitError,
)

try:
    result = client.evaluate("spawn", user_id="user123")
except SentinelRateLimitError as e:
    print(f"Rate limited, retry after {e.retry_after}s")
except SentinelAuthError:
    print("Invalid API key")
except SentinelConnectionError:
    print("Cannot reach Sentinel service")
except SentinelError as e:
    print(f"Sentinel error: {e}")
```

### Background Heartbeats

The SDK automatically sends heartbeats to keep the agent registered:

```python
client = SentinelClient(
    endpoint="https://sentinel.example.com",
    api_key="sk_agent_...",
    agent_type="jupyterhub",
    auto_heartbeat=True,
    heartbeat_interval=60,  # seconds
)
```

### Buffered Event Emission

Events are buffered and sent in batches for efficiency:

```python
client = SentinelClient(
    endpoint="https://sentinel.example.com",
    api_key="sk_agent_...",
    agent_type="jupyterhub",
    event_buffer_size=100,  # Max events before flush
    event_flush_interval=5,  # Seconds between flushes
)

# Events are queued and sent asynchronously
client.emit("ai_request", {
    "user_id": "user123",
    "provider": "openai",
    "model": "gpt-4",
    "input_tokens": 100,
    "output_tokens": 500,
})

# Force flush before shutdown
client.flush_events()
```

### Caching

Config and secrets are cached to reduce API calls:

```python
client = SentinelClient(
    endpoint="https://sentinel.example.com",
    api_key="sk_agent_...",
    agent_type="jupyterhub",
    config_cache_ttl=300,  # 5 minutes
    secrets_cache_ttl=60,  # 1 minute
)

# Force refresh cache
config = client.get_config(force_refresh=True)
secrets = client.get_secrets(force_refresh=True)
```

## API Reference

### SentinelClient

#### `__init__(endpoint, api_key, agent_type, **kwargs)`

Initialize the Sentinel client.

**Parameters:**
- `endpoint` (str): Sentinel API endpoint URL
- `api_key` (str): API key for authentication
- `agent_type` (str): Type of agent (jupyterhub, chat, langchain, etc.)
- `agent_id` (str, optional): Agent ID (generated on registration if not provided)
- `org_id` (str, optional): Organization ID
- `auto_heartbeat` (bool): Enable automatic heartbeats (default: True)
- `heartbeat_interval` (int): Seconds between heartbeats (default: 60)
- `timeout` (int): HTTP request timeout in seconds (default: 30)
- `retry_config` (RetryConfig, optional): Custom retry configuration

#### `register(capabilities, metadata=None, name=None)`

Register the agent with Sentinel. Returns config and API key.

#### `get_config(force_refresh=False)`

Get current configuration and policies.

#### `get_secrets(force_refresh=False)`

Get secrets this agent can access.

#### `evaluate(action, user_id=None, context=None)`

Evaluate policies for an action. Returns whether the action is allowed.

#### `emit(event_type, payload=None, category='telemetry', user_id=None)`

Emit an event (buffered, async).

#### `heartbeat(status='healthy', metrics=None)`

Send a heartbeat to Sentinel.

#### `shutdown()`

Graceful shutdown: stop threads and flush remaining events.

## License

MIT License - see [LICENSE](LICENSE) for details.
