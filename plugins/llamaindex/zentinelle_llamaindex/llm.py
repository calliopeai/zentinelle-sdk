"""
Governed LLM wrapper for LlamaIndex.
"""

from typing import Any, Optional, Sequence

from llama_index.core.base.llms.types import (
    ChatMessage,
    ChatResponse,
    CompletionResponse,
    LLMMetadata,
)
from llama_index.core.callbacks import CallbackManager
from llama_index.core.llms import LLM
from llama_index.core.llms.callbacks import llm_chat_callback, llm_completion_callback
from zentinelle import ZentinelleClient
from zentinelle.types import EvaluateResult, ModelUsage


class LLMBlockedError(Exception):
    """Raised when an LLM call is blocked by policy."""

    def __init__(self, reason: str, result: EvaluateResult):
        self.reason = reason
        self.result = result
        super().__init__(f"LLM call blocked: {reason}")


class GovernedLLM(LLM):
    """
    A LlamaIndex LLM wrapper with Zentinelle governance.

    Provides governance for LLM calls:
    - Model access control
    - Token limits
    - Cost tracking
    - Content filtering

    Example:
        from llama_index.llms.openai import OpenAI

        client = ZentinelleClient(api_key="...", agent_id="...")
        base_llm = OpenAI(model="gpt-4")

        llm = GovernedLLM(
            client=client,
            llm=base_llm,
            max_tokens_per_request=4000,
            max_cost_per_request=0.50
        )

        response = llm.complete("Write a summary")
    """

    def __init__(
        self,
        client: ZentinelleClient,
        llm: LLM,
        max_tokens_per_request: Optional[int] = None,
        max_cost_per_request: Optional[float] = None,
        allowed_models: Optional[list[str]] = None,
        user_id: Optional[str] = None,
        callback_manager: Optional[CallbackManager] = None,
    ):
        """
        Initialize a governed LLM.

        Args:
            client: Zentinelle client instance
            llm: Base LlamaIndex LLM to wrap
            max_tokens_per_request: Maximum tokens per request
            max_cost_per_request: Maximum cost per request
            allowed_models: List of allowed model IDs
            user_id: User ID for tracking
            callback_manager: Optional callback manager
        """
        super().__init__(callback_manager=callback_manager)
        self._client = client
        self._llm = llm
        self._max_tokens_per_request = max_tokens_per_request
        self._max_cost_per_request = max_cost_per_request
        self._allowed_models = allowed_models
        self._user_id = user_id

        self._total_tokens = 0
        self._total_cost = 0.0

    @property
    def metadata(self) -> LLMMetadata:
        """Get LLM metadata from underlying model."""
        return self._llm.metadata

    @property
    def zentinelle_client(self) -> ZentinelleClient:
        """Get the Zentinelle client."""
        return self._client

    def _check_policy(self, estimated_tokens: Optional[int] = None) -> EvaluateResult:
        """Check if LLM call is allowed."""
        model = self._llm.metadata.model_name

        # Check allowed models
        if self._allowed_models and model not in self._allowed_models:
            return EvaluateResult(
                allowed=False,
                reason=f"Model '{model}' not in allowed list: {self._allowed_models}",
                policies=[],
            )

        context = {
            "model": model,
            "estimated_tokens": estimated_tokens,
            "max_tokens_per_request": self._max_tokens_per_request,
            "max_cost_per_request": self._max_cost_per_request,
            "total_tokens": self._total_tokens,
            "total_cost": self._total_cost,
            "user_id": self._user_id,
        }

        return self._client.evaluate("llm_request", context=context)

    def _record_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cost: Optional[float] = None,
    ) -> None:
        """Record token and cost usage."""
        self._total_tokens += input_tokens + output_tokens
        if cost:
            self._total_cost += cost

        self._client.emit(
            category="model_request",
            action=self._llm.metadata.model_name,
            success=True,
            model_usage=ModelUsage(
                model=self._llm.metadata.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
            ),
            metadata={"user_id": self._user_id},
        )

    @llm_completion_callback()
    def complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponse:
        """Complete a prompt with governance."""
        # Estimate tokens
        estimated_tokens = len(prompt) // 4

        # Check policy
        result = self._check_policy(estimated_tokens)
        if not result.allowed:
            self._client.emit(
                category="policy_evaluation",
                action="llm_blocked",
                success=False,
                metadata={
                    "reason": result.reason,
                    "model": self._llm.metadata.model_name,
                    "user_id": self._user_id,
                },
            )
            raise LLMBlockedError(result.reason, result)

        # Execute completion
        response = self._llm.complete(prompt, formatted=formatted, **kwargs)

        # Record usage
        if hasattr(response, "raw") and response.raw:
            usage = getattr(response.raw, "usage", None)
            if usage:
                self._record_usage(
                    input_tokens=getattr(usage, "prompt_tokens", estimated_tokens),
                    output_tokens=getattr(usage, "completion_tokens", 0),
                )
        else:
            # Estimate output tokens
            output_tokens = len(response.text) // 4
            self._record_usage(input_tokens=estimated_tokens, output_tokens=output_tokens)

        return response

    @llm_chat_callback()
    def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        """Chat with governance."""
        # Estimate tokens
        estimated_tokens = sum(len(m.content or "") // 4 for m in messages)

        # Check policy
        result = self._check_policy(estimated_tokens)
        if not result.allowed:
            self._client.emit(
                category="policy_evaluation",
                action="llm_blocked",
                success=False,
                metadata={
                    "reason": result.reason,
                    "model": self._llm.metadata.model_name,
                    "user_id": self._user_id,
                },
            )
            raise LLMBlockedError(result.reason, result)

        # Execute chat
        response = self._llm.chat(messages, **kwargs)

        # Record usage
        if hasattr(response, "raw") and response.raw:
            usage = getattr(response.raw, "usage", None)
            if usage:
                self._record_usage(
                    input_tokens=getattr(usage, "prompt_tokens", estimated_tokens),
                    output_tokens=getattr(usage, "completion_tokens", 0),
                )
        else:
            output_tokens = len(response.message.content or "") // 4
            self._record_usage(input_tokens=estimated_tokens, output_tokens=output_tokens)

        return response

    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        """Stream completion with governance."""
        # Estimate tokens
        estimated_tokens = len(prompt) // 4

        # Check policy
        result = self._check_policy(estimated_tokens)
        if not result.allowed:
            raise LLMBlockedError(result.reason, result)

        # Stream completion
        for chunk in self._llm.stream_complete(prompt, formatted=formatted, **kwargs):
            yield chunk

        # Record approximate usage (can't know exact without final response)
        self._record_usage(input_tokens=estimated_tokens, output_tokens=100)

    def stream_chat(self, messages: Sequence[ChatMessage], **kwargs: Any):
        """Stream chat with governance."""
        # Estimate tokens
        estimated_tokens = sum(len(m.content or "") // 4 for m in messages)

        # Check policy
        result = self._check_policy(estimated_tokens)
        if not result.allowed:
            raise LLMBlockedError(result.reason, result)

        # Stream chat
        for chunk in self._llm.stream_chat(messages, **kwargs):
            yield chunk

        # Record approximate usage
        self._record_usage(input_tokens=estimated_tokens, output_tokens=100)

    async def acomplete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponse:
        """Async completion with governance."""
        estimated_tokens = len(prompt) // 4
        result = self._check_policy(estimated_tokens)
        if not result.allowed:
            raise LLMBlockedError(result.reason, result)

        response = await self._llm.acomplete(prompt, formatted=formatted, **kwargs)
        output_tokens = len(response.text) // 4
        self._record_usage(input_tokens=estimated_tokens, output_tokens=output_tokens)
        return response

    async def achat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponse:
        """Async chat with governance."""
        estimated_tokens = sum(len(m.content or "") // 4 for m in messages)
        result = self._check_policy(estimated_tokens)
        if not result.allowed:
            raise LLMBlockedError(result.reason, result)

        response = await self._llm.achat(messages, **kwargs)
        output_tokens = len(response.message.content or "") // 4
        self._record_usage(input_tokens=estimated_tokens, output_tokens=output_tokens)
        return response

    def get_usage_summary(self) -> dict[str, Any]:
        """Get usage summary."""
        return {
            "total_tokens": self._total_tokens,
            "total_cost": self._total_cost,
            "model": self._llm.metadata.model_name,
        }

    def reset_usage(self) -> None:
        """Reset usage counters."""
        self._total_tokens = 0
        self._total_cost = 0.0
