"""
Zentinelle SDK - Python client library for AI agent governance and runtime control.

Zentinelle provides policy enforcement, configuration management, secrets delivery,
and observability for AI agents across any framework.

Usage:
    from zentinelle import ZentinelleClient

    client = ZentinelleClient(
        endpoint="https://api.zentinelle.ai",
        api_key="sk_agent_...",
        agent_type="langchain",
    )

    # Register on startup
    config = client.register(capabilities=["chat", "tools"])

    # Get secrets
    secrets = client.get_secrets()

    # Evaluate policies before actions
    result = client.evaluate("tool_call", user_id="user123", context={...})

    # Emit events (async, buffered)
    client.emit("tool_call", {"tool": "web_search", "user_id": "user123"})

Error Handling:
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
"""
from .client import (
    ZentinelleClient,
    ZentinelleError,
    ZentinelleConnectionError,
    ZentinelleAuthError,
    ZentinelleRateLimitError,
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
    'ZentinelleClient',
    # Errors
    'ZentinelleError',
    'ZentinelleConnectionError',
    'ZentinelleAuthError',
    'ZentinelleRateLimitError',
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
