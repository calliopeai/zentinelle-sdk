"""
Governed query engine for LlamaIndex.
"""

import time
from typing import Any, Optional, Sequence

from llama_index.core.base.base_query_engine import BaseQueryEngine
from llama_index.core.base.response.schema import RESPONSE_TYPE
from llama_index.core.prompts.mixin import PromptMixinType
from llama_index.core.schema import QueryBundle, NodeWithScore
from zentinelle import ZentinelleClient
from zentinelle.types import EvaluateResult, ModelUsage


class QueryBlockedError(Exception):
    """Raised when a query is blocked by policy."""

    def __init__(self, reason: str, result: EvaluateResult):
        self.reason = reason
        self.result = result
        super().__init__(f"Query blocked: {reason}")


class GovernedQueryEngine(BaseQueryEngine):
    """
    A LlamaIndex query engine with Zentinelle governance.

    Provides governance for RAG queries:
    - Query content filtering
    - Token/cost limits
    - Source attribution tracking
    - PII detection

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        index = VectorStoreIndex.from_documents(documents)
        base_engine = index.as_query_engine()

        engine = GovernedQueryEngine(
            client=client,
            engine=base_engine,
            max_tokens_per_query=4000,
            require_source_attribution=True
        )

        response = engine.query("What is the refund policy?")
    """

    def __init__(
        self,
        client: ZentinelleClient,
        engine: BaseQueryEngine,
        max_tokens_per_query: Optional[int] = None,
        max_queries_per_session: Optional[int] = None,
        require_source_attribution: bool = False,
        allowed_topics: Optional[list[str]] = None,
        blocked_topics: Optional[list[str]] = None,
        user_id: Optional[str] = None,
    ):
        """
        Initialize a governed query engine.

        Args:
            client: Zentinelle client instance
            engine: Base LlamaIndex query engine to wrap
            max_tokens_per_query: Maximum tokens per query
            max_queries_per_session: Maximum queries allowed in session
            require_source_attribution: Whether to require source tracking
            allowed_topics: Topics that are allowed (None = all)
            blocked_topics: Topics that are blocked
            user_id: User ID for tracking
        """
        super().__init__(callback_manager=engine.callback_manager)
        self._client = client
        self._engine = engine
        self._max_tokens_per_query = max_tokens_per_query
        self._max_queries_per_session = max_queries_per_session
        self._require_source_attribution = require_source_attribution
        self._allowed_topics = allowed_topics
        self._blocked_topics = blocked_topics or []
        self._user_id = user_id

        self._query_count = 0
        self._total_tokens = 0

    @property
    def zentinelle_client(self) -> ZentinelleClient:
        """Get the Zentinelle client."""
        return self._client

    def _get_prompt_modules(self) -> PromptMixinType:
        """Get prompt modules from underlying engine."""
        return self._engine._get_prompt_modules()

    def _check_query_policy(self, query_str: str) -> EvaluateResult:
        """Check if query is allowed by policy."""
        # Check query limit
        if (
            self._max_queries_per_session
            and self._query_count >= self._max_queries_per_session
        ):
            return EvaluateResult(
                allowed=False,
                reason=f"Query limit exceeded: {self._query_count} >= {self._max_queries_per_session}",
                policies=[],
            )

        context = {
            "query": query_str[:500],
            "query_length": len(query_str),
            "query_count": self._query_count,
            "total_tokens": self._total_tokens,
            "max_tokens_per_query": self._max_tokens_per_query,
            "allowed_topics": self._allowed_topics,
            "blocked_topics": self._blocked_topics,
            "user_id": self._user_id,
        }

        return self._client.evaluate("rag_query", context=context)

    def _query(self, query_bundle: QueryBundle) -> RESPONSE_TYPE:
        """Execute query with governance."""
        query_str = query_bundle.query_str

        # Check policy
        result = self._check_query_policy(query_str)
        if not result.allowed:
            self._client.emit(
                category="policy_evaluation",
                action="rag_query_blocked",
                success=False,
                metadata={
                    "query_preview": query_str[:200],
                    "reason": result.reason,
                    "user_id": self._user_id,
                },
            )
            raise QueryBlockedError(result.reason, result)

        # Execute query
        start_time = time.time()
        try:
            response = self._engine._query(query_bundle)
            duration_ms = int((time.time() - start_time) * 1000)

            self._query_count += 1

            # Track sources if required
            sources = []
            if self._require_source_attribution and hasattr(response, "source_nodes"):
                sources = [
                    {
                        "id": node.node_id,
                        "score": node.score,
                        "text_preview": node.text[:100] if node.text else None,
                    }
                    for node in response.source_nodes[:5]
                ]

            # Estimate token usage from response
            response_text = str(response)
            estimated_tokens = len(response_text) // 4  # Rough estimate

            self._total_tokens += estimated_tokens

            # Record success
            self._client.emit(
                category="model_request",
                action="rag_query",
                success=True,
                model_usage=ModelUsage(
                    model="llamaindex",
                    input_tokens=len(query_str) // 4,
                    output_tokens=estimated_tokens,
                ),
                metadata={
                    "query_count": self._query_count,
                    "duration_ms": duration_ms,
                    "source_count": len(sources),
                    "sources": sources if sources else None,
                    "user_id": self._user_id,
                },
            )

            return response

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)

            self._client.emit(
                category="model_request",
                action="rag_query",
                success=False,
                metadata={
                    "duration_ms": duration_ms,
                    "error": str(e)[:500],
                    "user_id": self._user_id,
                },
            )
            raise

    async def _aquery(self, query_bundle: QueryBundle) -> RESPONSE_TYPE:
        """Execute async query with governance."""
        query_str = query_bundle.query_str

        # Check policy
        result = self._check_query_policy(query_str)
        if not result.allowed:
            self._client.emit(
                category="policy_evaluation",
                action="rag_query_blocked",
                success=False,
                metadata={
                    "query_preview": query_str[:200],
                    "reason": result.reason,
                    "user_id": self._user_id,
                },
            )
            raise QueryBlockedError(result.reason, result)

        # Execute query
        start_time = time.time()
        try:
            response = await self._engine._aquery(query_bundle)
            duration_ms = int((time.time() - start_time) * 1000)

            self._query_count += 1

            # Track sources
            sources = []
            if self._require_source_attribution and hasattr(response, "source_nodes"):
                sources = [
                    {
                        "id": node.node_id,
                        "score": node.score,
                    }
                    for node in response.source_nodes[:5]
                ]

            # Record success
            self._client.emit(
                category="model_request",
                action="rag_query",
                success=True,
                metadata={
                    "query_count": self._query_count,
                    "duration_ms": duration_ms,
                    "source_count": len(sources),
                    "user_id": self._user_id,
                },
            )

            return response

        except Exception as e:
            self._client.emit(
                category="model_request",
                action="rag_query",
                success=False,
                metadata={"error": str(e)[:500], "user_id": self._user_id},
            )
            raise

    def reset_session(self) -> None:
        """Reset session counters."""
        self._query_count = 0
        self._total_tokens = 0

    def get_usage_summary(self) -> dict[str, Any]:
        """Get usage summary for current session."""
        return {
            "query_count": self._query_count,
            "total_tokens": self._total_tokens,
            "queries_remaining": (self._max_queries_per_session - self._query_count)
            if self._max_queries_per_session
            else None,
        }
