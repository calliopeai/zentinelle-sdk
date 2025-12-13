"""
LangChain guardrails for Zentinelle policy enforcement.
"""
import logging
from typing import Any, Dict, List, Optional, Callable, Union
from functools import wraps

from langchain_core.tools import BaseTool
from langchain_core.runnables import Runnable, RunnableConfig

from zentinelle import ZentinelleClient, EvaluateResult

logger = logging.getLogger(__name__)


class PolicyViolationError(Exception):
    """Raised when a policy blocks an action."""
    def __init__(self, message: str, result: EvaluateResult):
        super().__init__(message)
        self.result = result


class ZentinelleGuardrail(Runnable):
    """
    LangChain Runnable that enforces Zentinelle policies.

    Use as input guardrail to check policies before chain execution,
    and output guardrail to filter/modify responses.

    Usage:
        from zentinelle_langchain import ZentinelleGuardrail

        client = ZentinelleClient(api_key="...", agent_type="langchain")
        guardrail = ZentinelleGuardrail(client)

        # As input filter
        chain = guardrail | prompt | llm

        # As output filter
        chain = prompt | llm | guardrail.output()
    """

    def __init__(
        self,
        client: ZentinelleClient,
        action: str = "chain_input",
        user_id_key: str = "user_id",
        raise_on_block: bool = True,
        block_message: str = "This request has been blocked by policy.",
    ):
        """
        Initialize guardrail.

        Args:
            client: ZentinelleClient instance
            action: Action name for policy evaluation
            user_id_key: Key to extract user_id from input
            raise_on_block: Raise exception on block (vs return error message)
            block_message: Message to return/raise when blocked
        """
        self.client = client
        self.action = action
        self.user_id_key = user_id_key
        self.raise_on_block = raise_on_block
        self.block_message = block_message

    def invoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
    ) -> Any:
        """Evaluate policy and pass through if allowed."""
        # Extract user_id if present
        user_id = None
        if isinstance(input, dict):
            user_id = input.get(self.user_id_key)

        # Build context from input
        context = {}
        if isinstance(input, dict):
            context = {k: v for k, v in input.items() if k != self.user_id_key}
        elif isinstance(input, str):
            context = {'input': input[:1000]}  # Truncate for policy eval

        # Evaluate policy
        result = self.client.evaluate(
            action=self.action,
            user_id=user_id,
            context=context,
        )

        if not result.allowed:
            if self.raise_on_block:
                raise PolicyViolationError(
                    result.reason or self.block_message,
                    result,
                )
            # Return error response instead of raising
            return {'error': result.reason or self.block_message, 'blocked': True}

        # Log warnings if any
        for warning in result.warnings:
            logger.warning(f"Policy warning: {warning}")

        return input

    async def ainvoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
    ) -> Any:
        """Async version of invoke."""
        # For now, run sync version (ZentinelleClient is sync)
        return self.invoke(input, config)

    def output(
        self,
        action: str = "chain_output",
        content_key: str = "content",
    ) -> 'ZentinelleOutputGuardrail':
        """
        Create output guardrail for filtering responses.

        Args:
            action: Action name for output policy evaluation
            content_key: Key to extract content from output

        Returns:
            ZentinelleOutputGuardrail instance
        """
        return ZentinelleOutputGuardrail(
            client=self.client,
            action=action,
            content_key=content_key,
            raise_on_block=self.raise_on_block,
            block_message=self.block_message,
        )


class ZentinelleOutputGuardrail(Runnable):
    """Output guardrail for filtering chain responses."""

    def __init__(
        self,
        client: ZentinelleClient,
        action: str = "chain_output",
        content_key: str = "content",
        raise_on_block: bool = True,
        block_message: str = "This response has been filtered by policy.",
    ):
        self.client = client
        self.action = action
        self.content_key = content_key
        self.raise_on_block = raise_on_block
        self.block_message = block_message

    def invoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
    ) -> Any:
        """Evaluate policy on output."""
        # Extract content for evaluation
        content = input
        if isinstance(input, dict):
            content = input.get(self.content_key, str(input))
        elif hasattr(input, 'content'):
            content = input.content

        result = self.client.evaluate(
            action=self.action,
            context={'output': str(content)[:2000]},
        )

        if not result.allowed:
            if self.raise_on_block:
                raise PolicyViolationError(
                    result.reason or self.block_message,
                    result,
                )
            return self.block_message

        return input

    async def ainvoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
    ) -> Any:
        return self.invoke(input, config)


class ZentinelleToolWrapper:
    """
    Wrapper to add Zentinelle policy enforcement to LangChain tools.

    Usage:
        from langchain.tools import DuckDuckGoSearchRun
        from zentinelle_langchain import ZentinelleToolWrapper

        search = DuckDuckGoSearchRun()
        wrapper = ZentinelleToolWrapper(client)
        safe_search = wrapper.wrap(search)

        # Or wrap multiple tools
        tools = wrapper.wrap_all([search, calculator, browser])
    """

    def __init__(
        self,
        client: ZentinelleClient,
        raise_on_block: bool = True,
        block_message: str = "Tool execution blocked by policy.",
    ):
        self.client = client
        self.raise_on_block = raise_on_block
        self.block_message = block_message

    def wrap(self, tool: BaseTool) -> BaseTool:
        """
        Wrap a tool with policy enforcement.

        Args:
            tool: LangChain tool to wrap

        Returns:
            Wrapped tool with policy checks
        """
        original_run = tool._run
        wrapper = self

        @wraps(original_run)
        def wrapped_run(*args, **kwargs):
            # Evaluate policy before running
            result = wrapper.client.evaluate(
                action='tool_call',
                context={
                    'tool': tool.name,
                    'args': str(args)[:500],
                    'kwargs': {k: str(v)[:100] for k, v in kwargs.items()},
                },
            )

            if not result.allowed:
                if wrapper.raise_on_block:
                    raise PolicyViolationError(
                        result.reason or wrapper.block_message,
                        result,
                    )
                return f"Tool blocked: {result.reason or wrapper.block_message}"

            # Run original tool
            output = original_run(*args, **kwargs)

            # Emit tool usage event
            wrapper.client.emit_tool_call(
                tool_name=tool.name,
                inputs={'args': str(args)[:500]},
                outputs={'result': str(output)[:500]},
            )

            return output

        tool._run = wrapped_run
        return tool

    def wrap_all(self, tools: List[BaseTool]) -> List[BaseTool]:
        """Wrap multiple tools with policy enforcement."""
        return [self.wrap(tool) for tool in tools]
