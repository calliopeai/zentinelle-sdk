"""
LangChain callback handler for Zentinelle observability.
"""
import logging
import time
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.messages import BaseMessage

from zentinelle import ZentinelleClient, ModelUsage

logger = logging.getLogger(__name__)

# Maximum age for timing entries before cleanup (5 minutes)
_MAX_TIMING_AGE_SECONDS = 300
# Maximum number of timing entries before forced cleanup
_MAX_TIMING_ENTRIES = 1000


class ZentinelleCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback handler that sends telemetry to Zentinelle.

    Tracks:
    - LLM calls (model, tokens, duration)
    - Tool invocations
    - Chain execution
    - Agent actions

    Usage:
        from langchain_openai import ChatOpenAI
        from zentinelle_langchain import ZentinelleCallbackHandler

        handler = ZentinelleCallbackHandler(
            api_key="sk_agent_...",
            agent_type="langchain",
        )

        llm = ChatOpenAI(callbacks=[handler])
        result = llm.invoke("Hello!")
    """

    def __init__(
        self,
        api_key: str,
        agent_type: str = "langchain",
        endpoint: Optional[str] = None,
        user_id: Optional[str] = None,
        track_prompts: bool = False,
        track_completions: bool = False,
        **client_kwargs,
    ):
        """
        Initialize callback handler.

        Args:
            api_key: Zentinelle API key
            agent_type: Agent type identifier
            endpoint: Custom Zentinelle endpoint
            user_id: Default user ID for events
            track_prompts: Include prompts in events (may contain PII)
            track_completions: Include completions in events
            **client_kwargs: Additional args for ZentinelleClient
        """
        super().__init__()
        self.client = ZentinelleClient(
            api_key=api_key,
            agent_type=agent_type,
            endpoint=endpoint,
            **client_kwargs,
        )
        self.user_id = user_id
        self.track_prompts = track_prompts
        self.track_completions = track_completions

        # Track timing with cleanup to prevent memory leaks
        self._start_times: Dict[UUID, float] = {}
        self._last_cleanup_time = time.time()

    def _cleanup_stale_timings(self) -> None:
        """Remove stale timing entries to prevent memory leaks."""
        now = time.time()

        # Only cleanup if enough time has passed or buffer is too large
        if (now - self._last_cleanup_time < 60 and
                len(self._start_times) < _MAX_TIMING_ENTRIES):
            return

        self._last_cleanup_time = now
        cutoff = now - _MAX_TIMING_AGE_SECONDS

        # Remove entries older than cutoff
        stale_ids = [
            run_id for run_id, start_time in self._start_times.items()
            if start_time < cutoff
        ]
        for run_id in stale_ids:
            del self._start_times[run_id]

        if stale_ids:
            logger.debug(f"Cleaned up {len(stale_ids)} stale timing entries")

    def register(
        self,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ):
        """Register the agent with Zentinelle."""
        return self.client.register(
            capabilities=capabilities or ["chat", "tools"],
            metadata=metadata,
        )

    # =========================================================================
    # Provider Detection
    # =========================================================================

    # Model name patterns for provider detection
    _PROVIDER_PATTERNS = {
        'openai': ['gpt-', 'text-davinci', 'text-curie', 'text-babbage', 'text-ada', 'o1-', 'chatgpt'],
        'anthropic': ['claude-', 'anthropic'],
        'google': ['gemini-', 'palm-', 'bison', 'gecko'],
        'cohere': ['command', 'cohere'],
        'mistral': ['mistral', 'mixtral'],
        'meta': ['llama', 'codellama'],
        'together': ['togethercomputer/', 'together/'],
        'groq': ['groq/'],
        'fireworks': ['fireworks/', 'accounts/fireworks'],
        'huggingface': ['huggingface/', 'hf/'],
        'deepseek': ['deepseek'],
        'ai21': ['j2-', 'jamba'],
        'perplexity': ['pplx-', 'sonar'],
        'aws_bedrock': ['amazon.', 'bedrock/'],
        'azure_openai': ['azure/'],
    }

    def _detect_provider(
        self,
        model: str,
        llm_output: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Detect AI provider from model name or response metadata.

        Args:
            model: Model name/identifier
            llm_output: LLM response output dict

        Returns:
            Provider slug (e.g., 'openai', 'anthropic')
        """
        model_lower = model.lower() if model else ''

        # Check llm_output for explicit provider info
        if llm_output:
            # Some LangChain integrations include provider in output
            if 'provider' in llm_output:
                return llm_output['provider']
            if 'model_provider' in llm_output:
                return llm_output['model_provider']
            # OpenAI specific
            if 'system_fingerprint' in llm_output:
                return 'openai'

        # Match model name against known patterns
        for provider, patterns in self._PROVIDER_PATTERNS.items():
            for pattern in patterns:
                if pattern in model_lower:
                    return provider

        # Fallback to unknown
        return 'unknown'

    # =========================================================================
    # LLM Callbacks
    # =========================================================================

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM starts running."""
        self._cleanup_stale_timings()
        self._start_times[run_id] = time.time()

        payload = {
            'model': serialized.get('kwargs', {}).get('model_name', 'unknown'),
            'provider': serialized.get('id', ['unknown'])[-1],
        }

        if self.track_prompts:
            payload['prompts'] = prompts

        self.client.emit(
            'llm_start',
            payload,
            category='telemetry',
            user_id=self.user_id,
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM ends running."""
        duration_ms = None
        if run_id in self._start_times:
            duration_ms = int((time.time() - self._start_times.pop(run_id)) * 1000)

        # Extract token usage if available
        token_usage = response.llm_output.get('token_usage', {}) if response.llm_output else {}
        model = response.llm_output.get('model_name', 'unknown') if response.llm_output else 'unknown'

        input_tokens = token_usage.get('prompt_tokens', 0)
        output_tokens = token_usage.get('completion_tokens', 0)

        # Detect provider from model name or response metadata
        provider = self._detect_provider(model, response.llm_output)

        # Track usage for cost policies
        if input_tokens or output_tokens:
            self.client.track_usage(ModelUsage(
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ))

        payload = {
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'duration_ms': duration_ms,
        }

        if self.track_completions and response.generations:
            payload['completions'] = [
                gen.text for gen in response.generations[0]
            ]

        self.client.emit(
            'llm_end',
            payload,
            category='telemetry',
            user_id=self.user_id,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM errors."""
        self._start_times.pop(run_id, None)

        self.client.emit(
            'llm_error',
            {
                'error_type': type(error).__name__,
                'error_message': str(error)[:500],
            },
            category='alert',
            user_id=self.user_id,
        )

    # =========================================================================
    # Chat Model Callbacks
    # =========================================================================

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Called when chat model starts."""
        self._cleanup_stale_timings()
        self._start_times[run_id] = time.time()

        payload = {
            'model': serialized.get('kwargs', {}).get('model_name', 'unknown'),
            'provider': serialized.get('id', ['unknown'])[-1],
            'message_count': sum(len(m) for m in messages),
        }

        self.client.emit(
            'chat_model_start',
            payload,
            category='telemetry',
            user_id=self.user_id,
        )

    # =========================================================================
    # Tool Callbacks
    # =========================================================================

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        inputs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Called when tool starts running."""
        self._cleanup_stale_timings()
        self._start_times[run_id] = time.time()

        tool_name = serialized.get('name', 'unknown')

        self.client.emit(
            'tool_start',
            {
                'tool': tool_name,
                'input_length': len(input_str),
            },
            category='audit',
            user_id=self.user_id,
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when tool ends running."""
        duration_ms = None
        if run_id in self._start_times:
            duration_ms = int((time.time() - self._start_times.pop(run_id)) * 1000)

        self.client.emit(
            'tool_end',
            {
                'output_length': len(str(output)),
                'duration_ms': duration_ms,
            },
            category='audit',
            user_id=self.user_id,
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when tool errors."""
        self._start_times.pop(run_id, None)

        self.client.emit(
            'tool_error',
            {
                'error_type': type(error).__name__,
                'error_message': str(error)[:500],
            },
            category='alert',
            user_id=self.user_id,
        )

    # =========================================================================
    # Chain Callbacks
    # =========================================================================

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Called when chain starts running."""
        self._cleanup_stale_timings()
        self._start_times[run_id] = time.time()

        chain_name = serialized.get('name', serialized.get('id', ['unknown'])[-1])

        self.client.emit(
            'chain_start',
            {
                'chain': chain_name,
                'is_root': parent_run_id is None,
            },
            category='telemetry',
            user_id=self.user_id,
        )

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when chain ends running."""
        duration_ms = None
        if run_id in self._start_times:
            duration_ms = int((time.time() - self._start_times.pop(run_id)) * 1000)

        self.client.emit(
            'chain_end',
            {
                'duration_ms': duration_ms,
                'is_root': parent_run_id is None,
            },
            category='telemetry',
            user_id=self.user_id,
        )

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when chain errors."""
        self._start_times.pop(run_id, None)

        self.client.emit(
            'chain_error',
            {
                'error_type': type(error).__name__,
                'error_message': str(error)[:500],
            },
            category='alert',
            user_id=self.user_id,
        )

    # =========================================================================
    # Agent Callbacks
    # =========================================================================

    def on_agent_action(
        self,
        action: AgentAction,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when agent takes an action."""
        self.client.emit(
            'agent_action',
            {
                'tool': action.tool,
                'log': action.log[:500] if action.log else None,
            },
            category='audit',
            user_id=self.user_id,
        )

    def on_agent_finish(
        self,
        finish: AgentFinish,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when agent finishes."""
        self.client.emit(
            'agent_finish',
            {
                'has_output': bool(finish.return_values),
            },
            category='audit',
            user_id=self.user_id,
        )

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def shutdown(self):
        """Shutdown the client and flush events."""
        self.client.shutdown()
