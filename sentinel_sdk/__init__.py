"""
Sentinel SDK - Python client library for AI agent integration.

Sentinel is an agent endpoint management platform that provides policy
enforcement, configuration management, secrets delivery, and telemetry
for AI agents.

Usage:
    from sentinel_sdk import SentinelClient

    client = SentinelClient(
        endpoint="https://sentinel.example.com",
        api_key="sk_agent_...",
        agent_type="jupyterhub",
    )

    # Register on startup
    config = client.register(capabilities=["lab", "chat"])

    # Get secrets
    secrets = client.get_secrets()

    # Evaluate policies before actions
    result = client.evaluate("spawn", user_id="user123", context={...})

    # Emit events (async, buffered)
    client.emit("spawn", {"user_id": "user123"})

Error Handling:
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
"""
from .client import (
    SentinelClient,
    SentinelError,
    SentinelConnectionError,
    SentinelAuthError,
    SentinelRateLimitError,
    RetryConfig,
    CircuitBreaker,
)
from .types import (
    EvaluateResult,
    PolicyConfig,
    RegisterResult,
    ConfigResult,
    SecretsResult,
    EventsResult,
)

__all__ = [
    # Client
    'SentinelClient',
    # Errors
    'SentinelError',
    'SentinelConnectionError',
    'SentinelAuthError',
    'SentinelRateLimitError',
    # Config
    'RetryConfig',
    'CircuitBreaker',
    # Types
    'EvaluateResult',
    'PolicyConfig',
    'RegisterResult',
    'ConfigResult',
    'SecretsResult',
    'EventsResult',
]

__version__ = '0.1.0'
