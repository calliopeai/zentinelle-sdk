"""
LangChain Runnable wrapper for full chain governance.
"""
import logging
from typing import Any, Dict, List, Optional, Iterator, AsyncIterator

from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.callbacks import CallbackManagerForChainRun

from zentinelle import ZentinelleClient

logger = logging.getLogger(__name__)


class ZentinelleRunnable(Runnable):
    """
    Wrap any LangChain Runnable with Zentinelle governance.

    Provides:
    - Input policy evaluation
    - Output policy evaluation
    - Automatic event emission
    - Rate limiting enforcement
    - Model restrictions

    Usage:
        from langchain_openai import ChatOpenAI
        from zentinelle_langchain import ZentinelleRunnable

        llm = ChatOpenAI()
        governed_llm = ZentinelleRunnable(
            runnable=llm,
            api_key="sk_agent_...",
            agent_type="langchain",
        )

        # Use like any other runnable
        result = governed_llm.invoke("Hello!")
    """

    def __init__(
        self,
        runnable: Runnable,
        api_key: str,
        agent_type: str = "langchain",
        endpoint: Optional[str] = None,
        evaluate_input: bool = True,
        evaluate_output: bool = True,
        fail_open: bool = False,
        **client_kwargs,
    ):
        """
        Initialize governed runnable.

        Args:
            runnable: The LangChain Runnable to wrap
            api_key: Zentinelle API key
            agent_type: Agent type identifier
            endpoint: Custom Zentinelle endpoint
            evaluate_input: Evaluate policies on input
            evaluate_output: Evaluate policies on output
            fail_open: Allow execution if Zentinelle unreachable
            **client_kwargs: Additional ZentinelleClient args
        """
        self.runnable = runnable
        self.evaluate_input = evaluate_input
        self.evaluate_output = evaluate_output

        self.client = ZentinelleClient(
            api_key=api_key,
            agent_type=agent_type,
            endpoint=endpoint,
            fail_open=fail_open,
            **client_kwargs,
        )

    def invoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
    ) -> Any:
        """Invoke with governance."""
        import time
        start_time = time.time()

        # Extract context
        context = self._extract_context(input)
        user_id = context.pop('user_id', None)

        # Input policy evaluation
        if self.evaluate_input:
            result = self.client.evaluate(
                action='runnable_input',
                user_id=user_id,
                context=context,
            )
            if not result.allowed:
                self.client.emit('runnable_blocked', {
                    'stage': 'input',
                    'reason': result.reason,
                }, category='audit', user_id=user_id)
                raise ValueError(f"Input blocked by policy: {result.reason}")

        # Emit start event
        self.client.emit('runnable_start', {
            'runnable_type': type(self.runnable).__name__,
        }, category='telemetry', user_id=user_id)

        try:
            # Execute wrapped runnable
            output = self.runnable.invoke(input, config)

            # Output policy evaluation
            if self.evaluate_output:
                output_context = self._extract_context(output)
                result = self.client.evaluate(
                    action='runnable_output',
                    user_id=user_id,
                    context=output_context,
                )
                if not result.allowed:
                    self.client.emit('runnable_blocked', {
                        'stage': 'output',
                        'reason': result.reason,
                    }, category='audit', user_id=user_id)
                    raise ValueError(f"Output blocked by policy: {result.reason}")

            # Emit success event
            duration_ms = int((time.time() - start_time) * 1000)
            self.client.emit('runnable_end', {
                'runnable_type': type(self.runnable).__name__,
                'duration_ms': duration_ms,
                'success': True,
            }, category='telemetry', user_id=user_id)

            return output

        except Exception as e:
            # Emit error event
            duration_ms = int((time.time() - start_time) * 1000)
            self.client.emit('runnable_error', {
                'runnable_type': type(self.runnable).__name__,
                'duration_ms': duration_ms,
                'error_type': type(e).__name__,
                'error_message': str(e)[:500],
            }, category='alert', user_id=user_id)
            raise

    async def ainvoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
    ) -> Any:
        """Async invoke with governance."""
        # For now, delegate to sync (client is sync)
        return self.invoke(input, config)

    def stream(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
    ) -> Iterator[Any]:
        """Stream with governance."""
        context = self._extract_context(input)
        user_id = context.pop('user_id', None)

        # Input policy evaluation
        if self.evaluate_input:
            result = self.client.evaluate(
                action='runnable_input',
                user_id=user_id,
                context=context,
            )
            if not result.allowed:
                raise ValueError(f"Input blocked by policy: {result.reason}")

        # Stream from wrapped runnable
        for chunk in self.runnable.stream(input, config):
            yield chunk

    async def astream(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[Any]:
        """Async stream with governance."""
        context = self._extract_context(input)
        user_id = context.pop('user_id', None)

        if self.evaluate_input:
            result = self.client.evaluate(
                action='runnable_input',
                user_id=user_id,
                context=context,
            )
            if not result.allowed:
                raise ValueError(f"Input blocked by policy: {result.reason}")

        async for chunk in self.runnable.astream(input, config):
            yield chunk

    def batch(
        self,
        inputs: List[Any],
        config: Optional[RunnableConfig] = None,
        **kwargs,
    ) -> List[Any]:
        """Batch invoke with governance."""
        # Evaluate batch policy
        result = self.client.evaluate(
            action='runnable_batch',
            context={'batch_size': len(inputs)},
        )
        if not result.allowed:
            raise ValueError(f"Batch blocked by policy: {result.reason}")

        return self.runnable.batch(inputs, config, **kwargs)

    def _extract_context(self, value: Any) -> Dict[str, Any]:
        """Extract context dict from various input types."""
        if isinstance(value, dict):
            return {k: str(v)[:500] for k, v in value.items()}
        elif isinstance(value, str):
            return {'content': value[:1000]}
        elif hasattr(value, 'content'):
            return {'content': str(value.content)[:1000]}
        else:
            return {'value': str(value)[:1000]}

    @property
    def InputType(self):
        return self.runnable.InputType

    @property
    def OutputType(self):
        return self.runnable.OutputType

    def shutdown(self):
        """Shutdown the client."""
        self.client.shutdown()
