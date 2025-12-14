"""
Governed tool utilities for Microsoft Agent Framework.
"""
import logging
import time
from typing import Any, Callable, Dict, Optional, TypeVar, ParamSpec
from functools import wraps

from zentinelle import ZentinelleClient, EvaluateResult

logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


def _is_coroutine_function(func: Callable) -> bool:
    """Check if a function is a coroutine function."""
    import asyncio
    return asyncio.iscoroutinefunction(func)


class PolicyViolationError(Exception):
    """Raised when a tool call is blocked by policy."""
    def __init__(self, message: str, result: EvaluateResult):
        super().__init__(message)
        self.result = result


class ZentinelleToolPlugin:
    """
    Tool governance plugin for Microsoft Agent Framework.

    Wrap tools with policy enforcement and telemetry.

    Usage:
        from zentinelle_ms_agent import ZentinelleToolPlugin

        plugin = ZentinelleToolPlugin(api_key="sk_agent_...")

        @plugin.govern("web_search")
        async def search_web(query: str) -> str:
            # Tool implementation
            return results
    """

    def __init__(
        self,
        api_key: str,
        endpoint: Optional[str] = None,
        fail_open: bool = False,
        **client_kwargs,
    ):
        """
        Initialize tool plugin.

        Args:
            api_key: Zentinelle API key
            endpoint: Custom Zentinelle endpoint
            fail_open: Allow tool calls if Zentinelle unreachable
            **client_kwargs: Additional ZentinelleClient args
        """
        self.client = ZentinelleClient(
            api_key=api_key,
            agent_type="ms-agent-framework-tools",
            endpoint=endpoint,
            fail_open=fail_open,
            **client_kwargs,
        )
        self.fail_open = fail_open
        self._tool_configs: Dict[str, Dict] = {}

    def configure_tool(
        self,
        tool_name: str,
        require_user_id: bool = False,
        rate_limit: Optional[int] = None,
        allowed_users: Optional[list] = None,
        blocked_users: Optional[list] = None,
    ) -> None:
        """
        Configure governance for a specific tool.

        Args:
            tool_name: Tool name
            require_user_id: Require user_id for calls
            rate_limit: Calls per minute (None = unlimited)
            allowed_users: Whitelist of user IDs
            blocked_users: Blacklist of user IDs
        """
        self._tool_configs[tool_name] = {
            'require_user_id': require_user_id,
            'rate_limit': rate_limit,
            'allowed_users': allowed_users,
            'blocked_users': blocked_users,
        }

    def govern(
        self,
        tool_name: str,
        evaluate_args: bool = True,
        track_result: bool = True,
    ) -> Callable[[Callable[P, T]], Callable[P, T]]:
        """
        Decorator to add governance to a tool function.

        Args:
            tool_name: Name of the tool
            evaluate_args: Evaluate arguments against policies
            track_result: Track result in telemetry

        Returns:
            Decorated function
        """
        def decorator(func: Callable[P, T]) -> Callable[P, T]:
            @wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                return await self._execute_governed(
                    func, tool_name, evaluate_args, track_result,
                    *args, **kwargs
                )

            @wraps(func)
            def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                # For sync functions, run governance synchronously
                import asyncio
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(
                    self._execute_governed(
                        func, tool_name, evaluate_args, track_result,
                        *args, **kwargs
                    )
                )

            # Return appropriate wrapper based on function type
            if _is_coroutine_function(func):
                return async_wrapper
            return sync_wrapper

        return decorator

    async def _execute_governed(
        self,
        func: Callable,
        tool_name: str,
        evaluate_args: bool,
        track_result: bool,
        *args,
        **kwargs,
    ) -> Any:
        """Execute a governed tool call."""
        start_time = time.time()
        user_id = kwargs.pop('user_id', None)

        # Check local config
        config = self._tool_configs.get(tool_name, {})
        if config.get('require_user_id') and not user_id:
            raise ValueError(f"Tool '{tool_name}' requires user_id")

        if config.get('allowed_users') and user_id not in config['allowed_users']:
            raise PolicyViolationError(
                f"User not allowed to use tool '{tool_name}'",
                EvaluateResult(allowed=False, reason="User not in allowed list"),
            )

        if config.get('blocked_users') and user_id in config['blocked_users']:
            raise PolicyViolationError(
                f"User blocked from using tool '{tool_name}'",
                EvaluateResult(allowed=False, reason="User in blocked list"),
            )

        # Evaluate with Zentinelle
        if evaluate_args:
            result = self.client.evaluate(
                action='tool_call',
                user_id=user_id,
                context={
                    'tool': tool_name,
                    'args': str(args)[:500],
                    'kwargs': {k: str(v)[:200] for k, v in kwargs.items()},
                },
            )

            if not result.allowed and not self.fail_open:
                raise PolicyViolationError(
                    result.reason or f"Tool '{tool_name}' blocked by policy",
                    result,
                )

        # Execute tool
        try:
            if _is_coroutine_function(func):
                output = await func(*args, **kwargs)
            else:
                output = func(*args, **kwargs)

            duration_ms = int((time.time() - start_time) * 1000)

            # Track result
            if track_result:
                self.client.emit_tool_call(
                    tool_name=tool_name,
                    user_id=user_id,
                    inputs={'args_count': len(args), 'kwargs_count': len(kwargs)},
                    outputs={'result_type': type(output).__name__},
                    duration_ms=duration_ms,
                )

            return output

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)

            self.client.emit('tool_error', {
                'tool': tool_name,
                'error_type': type(e).__name__,
                'error_message': str(e)[:500],
                'duration_ms': duration_ms,
            }, category='alert', user_id=user_id)

            raise

    def shutdown(self) -> None:
        """Shutdown and flush events."""
        self.client.shutdown()


def governed_tool(
    client: ZentinelleClient,
    tool_name: str,
    fail_open: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Simple decorator for one-off tool governance.

    Usage:
        from zentinelle import ZentinelleClient
        from zentinelle_ms_agent import governed_tool

        client = ZentinelleClient(...)

        @governed_tool(client, "calculator")
        def calculate(expression: str) -> float:
            # WARNING: Use a safe math parser in production, never eval()
            import ast
            return ast.literal_eval(expression)  # Only evaluates literals
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            user_id = kwargs.pop('user_id', None)

            # Evaluate policy
            result = client.evaluate(
                action='tool_call',
                user_id=user_id,
                context={'tool': tool_name},
            )

            if not result.allowed and not fail_open:
                raise PolicyViolationError(
                    result.reason or f"Tool '{tool_name}' blocked",
                    result,
                )

            # Execute
            output = func(*args, **kwargs)

            # Track
            client.emit_tool_call(tool_name=tool_name, user_id=user_id)

            return output

        return wrapper
    return decorator
