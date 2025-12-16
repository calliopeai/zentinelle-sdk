"""
Microsoft Agent Framework extension for Zentinelle governance.
"""
import logging
import time
from typing import Any, Dict, List, Optional, Callable, Awaitable
from dataclasses import dataclass

from zentinelle import ZentinelleClient, EvaluateResult, ModelUsage

logger = logging.getLogger(__name__)


@dataclass
class GovernanceConfig:
    """Configuration for agent governance."""
    evaluate_messages: bool = True
    evaluate_tool_calls: bool = True
    track_token_usage: bool = True
    fail_open: bool = False
    block_message: str = "This action has been blocked by governance policy."


class PolicyViolationError(Exception):
    """Raised when a governance policy blocks an action."""
    def __init__(self, message: str, result: EvaluateResult):
        super().__init__(message)
        self.result = result


class ZentinelleAgentExtension:
    """
    Microsoft Agent Framework extension for Zentinelle governance.

    Integrates with the Agent Framework's extension system to provide:
    - Message-level policy evaluation
    - Tool call governance
    - Token usage tracking for cost policies
    - Compliance audit logging

    Usage:
        from agent_framework import Agent, ChatCompletionClient
        from zentinelle_ms_agent import ZentinelleAgentExtension

        extension = ZentinelleAgentExtension(
            api_key="sk_agent_...",
            agent_type="ms-agent-framework",
        )

        agent = Agent(
            name="assistant",
            client=ChatCompletionClient(...),
            extensions=[extension],
        )
    """

    def __init__(
        self,
        api_key: str,
        agent_type: str = "ms-agent-framework",
        endpoint: Optional[str] = None,
        config: Optional[GovernanceConfig] = None,
        **client_kwargs,
    ):
        """
        Initialize extension.

        Args:
            api_key: Zentinelle API key
            agent_type: Agent type identifier
            endpoint: Custom Zentinelle endpoint
            config: Governance configuration
            **client_kwargs: Additional ZentinelleClient args
        """
        self.client = ZentinelleClient(
            api_key=api_key,
            agent_type=agent_type,
            endpoint=endpoint,
            **client_kwargs,
        )
        self.config = config or GovernanceConfig()
        self._start_times: Dict[str, float] = {}

    async def register(
        self,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ):
        """Register agent with Zentinelle."""
        return self.client.register(
            capabilities=capabilities or ["chat", "tools", "multi-agent"],
            metadata=metadata,
        )

    # =========================================================================
    # Agent Lifecycle Hooks
    # =========================================================================

    async def on_agent_start(
        self,
        agent_name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Called when an agent starts processing."""
        self._start_times[agent_name] = time.time()

        self.client.emit('agent_start', {
            'agent_name': agent_name,
            'context': context or {},
        }, category='telemetry')

    async def on_agent_end(
        self,
        agent_name: str,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Called when an agent finishes processing."""
        duration_ms = None
        if agent_name in self._start_times:
            duration_ms = int((time.time() - self._start_times.pop(agent_name)) * 1000)

        self.client.emit('agent_end', {
            'agent_name': agent_name,
            'duration_ms': duration_ms,
            'success': success,
            'error': error,
        }, category='telemetry')

    # =========================================================================
    # Message Governance
    # =========================================================================

    async def evaluate_message(
        self,
        message: str,
        role: str = "user",
        user_id: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> EvaluateResult:
        """
        Evaluate a message against governance policies.

        Args:
            message: Message content to evaluate
            role: Message role (user, assistant, system)
            user_id: User identifier
            agent_name: Agent processing the message

        Returns:
            EvaluateResult with allowed status

        Raises:
            PolicyViolationError: If message is blocked and fail_open is False
        """
        if not self.config.evaluate_messages:
            return EvaluateResult(allowed=True)

        result = self.client.evaluate(
            action='message',
            user_id=user_id,
            context={
                'content': message[:2000],
                'role': role,
                'agent_name': agent_name,
            },
        )

        if not result.allowed and not self.config.fail_open:
            raise PolicyViolationError(
                result.reason or self.config.block_message,
                result,
            )

        return result

    async def on_message_received(
        self,
        message: Dict[str, Any],
        agent_name: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Hook called when agent receives a message.
        Can modify or block the message.

        Args:
            message: Message dict with 'content' and 'role'
            agent_name: Agent receiving the message
            user_id: User identifier

        Returns:
            Potentially modified message dict
        """
        content = message.get('content', '')
        role = message.get('role', 'user')

        await self.evaluate_message(
            message=str(content),
            role=role,
            user_id=user_id,
            agent_name=agent_name,
        )

        self.client.emit('message_received', {
            'agent_name': agent_name,
            'role': role,
            'content_length': len(str(content)),
        }, category='audit', user_id=user_id)

        return message

    async def on_message_sent(
        self,
        message: Dict[str, Any],
        agent_name: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Hook called when agent sends a message.
        Can modify or block the response.
        """
        content = message.get('content', '')
        role = message.get('role', 'assistant')

        result = await self.evaluate_message(
            message=str(content),
            role=role,
            user_id=user_id,
            agent_name=agent_name,
        )

        self.client.emit('message_sent', {
            'agent_name': agent_name,
            'role': role,
            'content_length': len(str(content)),
        }, category='audit', user_id=user_id)

        return message

    # =========================================================================
    # Tool Call Governance
    # =========================================================================

    async def evaluate_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> EvaluateResult:
        """
        Evaluate a tool call against governance policies.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            user_id: User identifier
            agent_name: Agent making the call

        Returns:
            EvaluateResult

        Raises:
            PolicyViolationError: If tool call is blocked
        """
        if not self.config.evaluate_tool_calls:
            return EvaluateResult(allowed=True)

        result = self.client.evaluate(
            action='tool_call',
            user_id=user_id,
            context={
                'tool': tool_name,
                'arguments': {k: str(v)[:200] for k, v in arguments.items()},
                'agent_name': agent_name,
            },
        )

        if not result.allowed and not self.config.fail_open:
            raise PolicyViolationError(
                result.reason or f"Tool '{tool_name}' blocked by policy",
                result,
            )

        return result

    async def on_tool_call_start(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        agent_name: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Hook called before a tool is executed."""
        call_id = f"{agent_name}:{tool_name}:{time.time()}"
        self._start_times[call_id] = time.time()

        await self.evaluate_tool_call(
            tool_name=tool_name,
            arguments=arguments,
            user_id=user_id,
            agent_name=agent_name,
        )

        self.client.emit('tool_call_start', {
            'agent_name': agent_name,
            'tool': tool_name,
        }, category='audit', user_id=user_id)

    async def on_tool_call_end(
        self,
        tool_name: str,
        result: Any,
        agent_name: str,
        user_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Hook called after a tool completes."""
        self.client.emit_tool_call(
            tool_name=tool_name,
            user_id=user_id,
            outputs={'result_type': type(result).__name__} if result else None,
        )

    # =========================================================================
    # Token Usage Tracking
    # =========================================================================

    async def track_completion(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent_name: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Track token usage for cost policies.

        Args:
            provider: Model provider (openai, azure, anthropic)
            model: Model identifier
            input_tokens: Input token count
            output_tokens: Output token count
            agent_name: Agent that made the request
            user_id: User identifier
        """
        if not self.config.track_token_usage:
            return

        self.client.track_usage(ModelUsage(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ))

        self.client.emit('model_completion', {
            'provider': provider,
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'agent_name': agent_name,
        }, category='telemetry', user_id=user_id)

    # =========================================================================
    # Multi-Agent Orchestration Hooks
    # =========================================================================

    async def on_handoff(
        self,
        from_agent: str,
        to_agent: str,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> EvaluateResult:
        """
        Evaluate an agent-to-agent handoff.

        Args:
            from_agent: Source agent name
            to_agent: Target agent name
            context: Handoff context
            user_id: User identifier

        Returns:
            EvaluateResult
        """
        result = self.client.evaluate(
            action='agent_handoff',
            user_id=user_id,
            context={
                'from_agent': from_agent,
                'to_agent': to_agent,
                'context': context or {},
            },
        )

        self.client.emit('agent_handoff', {
            'from_agent': from_agent,
            'to_agent': to_agent,
            'allowed': result.allowed,
        }, category='audit', user_id=user_id)

        if not result.allowed and not self.config.fail_open:
            raise PolicyViolationError(
                result.reason or f"Handoff from {from_agent} to {to_agent} blocked",
                result,
            )

        return result

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def shutdown(self) -> None:
        """Shutdown the client and flush events."""
        self.client.shutdown()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()
