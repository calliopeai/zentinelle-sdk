"""
Governed retriever for LlamaIndex.
"""

import time
from typing import Any, List, Optional

from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.callbacks.base import CallbackManager
from llama_index.core.schema import NodeWithScore, QueryBundle
from zentinelle import ZentinelleClient
from zentinelle.types import EvaluateResult


class RetrieverBlockedError(Exception):
    """Raised when retrieval is blocked by policy."""

    def __init__(self, reason: str, result: EvaluateResult):
        self.reason = reason
        self.result = result
        super().__init__(f"Retrieval blocked: {reason}")


class GovernedRetriever(BaseRetriever):
    """
    A LlamaIndex retriever with Zentinelle governance.

    Provides governance for document retrieval:
    - Access control by document/collection
    - Retrieval logging for audit
    - Result filtering
    - Rate limiting

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        index = VectorStoreIndex.from_documents(documents)
        base_retriever = index.as_retriever()

        retriever = GovernedRetriever(
            client=client,
            retriever=base_retriever,
            allowed_collections=["public", "internal"],
            max_results=10
        )

        nodes = retriever.retrieve("company policy")
    """

    def __init__(
        self,
        client: ZentinelleClient,
        retriever: BaseRetriever,
        allowed_collections: Optional[list[str]] = None,
        blocked_collections: Optional[list[str]] = None,
        max_results: Optional[int] = None,
        min_score_threshold: Optional[float] = None,
        user_id: Optional[str] = None,
        callback_manager: Optional[CallbackManager] = None,
    ):
        """
        Initialize a governed retriever.

        Args:
            client: Zentinelle client instance
            retriever: Base LlamaIndex retriever to wrap
            allowed_collections: Collections user can access (None = all)
            blocked_collections: Collections to block
            max_results: Maximum results to return
            min_score_threshold: Minimum similarity score
            user_id: User ID for access control
            callback_manager: Optional callback manager
        """
        super().__init__(callback_manager=callback_manager)
        self._client = client
        self._retriever = retriever
        self._allowed_collections = allowed_collections
        self._blocked_collections = blocked_collections or []
        self._max_results = max_results
        self._min_score_threshold = min_score_threshold
        self._user_id = user_id

        self._retrieval_count = 0

    @property
    def zentinelle_client(self) -> ZentinelleClient:
        """Get the Zentinelle client."""
        return self._client

    def _check_retrieval_policy(self, query_str: str) -> EvaluateResult:
        """Check if retrieval is allowed by policy."""
        context = {
            "query": query_str[:500],
            "allowed_collections": self._allowed_collections,
            "blocked_collections": self._blocked_collections,
            "user_id": self._user_id,
            "retrieval_count": self._retrieval_count,
        }

        return self._client.evaluate("rag_retrieval", context=context)

    def _filter_results(
        self, nodes: List[NodeWithScore]
    ) -> List[NodeWithScore]:
        """Filter results based on governance rules."""
        filtered = []

        for node in nodes:
            # Check score threshold
            if self._min_score_threshold and node.score:
                if node.score < self._min_score_threshold:
                    continue

            # Check collection access
            metadata = node.node.metadata or {}
            collection = metadata.get("collection")

            if collection:
                if self._blocked_collections and collection in self._blocked_collections:
                    continue
                if (
                    self._allowed_collections
                    and collection not in self._allowed_collections
                ):
                    continue

            filtered.append(node)

        # Apply max results
        if self._max_results:
            filtered = filtered[: self._max_results]

        return filtered

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        """Execute retrieval with governance."""
        query_str = query_bundle.query_str

        # Check policy
        result = self._check_retrieval_policy(query_str)
        if not result.allowed:
            self._client.emit(
                category="policy_evaluation",
                action="rag_retrieval_blocked",
                success=False,
                metadata={
                    "query_preview": query_str[:200],
                    "reason": result.reason,
                    "user_id": self._user_id,
                },
            )
            raise RetrieverBlockedError(result.reason, result)

        # Execute retrieval
        start_time = time.time()
        try:
            nodes = self._retriever._retrieve(query_bundle)
            duration_ms = int((time.time() - start_time) * 1000)

            # Filter results
            original_count = len(nodes)
            nodes = self._filter_results(nodes)
            filtered_count = original_count - len(nodes)

            self._retrieval_count += 1

            # Record retrieval
            self._client.emit(
                category="tool_call",
                action="rag_retrieval",
                success=True,
                metadata={
                    "query_preview": query_str[:200],
                    "results_returned": len(nodes),
                    "results_filtered": filtered_count,
                    "duration_ms": duration_ms,
                    "user_id": self._user_id,
                    "top_scores": [n.score for n in nodes[:3] if n.score],
                },
            )

            return nodes

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)

            self._client.emit(
                category="tool_call",
                action="rag_retrieval",
                success=False,
                metadata={
                    "duration_ms": duration_ms,
                    "error": str(e)[:500],
                    "user_id": self._user_id,
                },
            )
            raise

    async def _aretrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        """Execute async retrieval with governance."""
        query_str = query_bundle.query_str

        # Check policy
        result = self._check_retrieval_policy(query_str)
        if not result.allowed:
            raise RetrieverBlockedError(result.reason, result)

        # Execute retrieval
        start_time = time.time()
        try:
            nodes = await self._retriever._aretrieve(query_bundle)
            duration_ms = int((time.time() - start_time) * 1000)

            # Filter results
            nodes = self._filter_results(nodes)
            self._retrieval_count += 1

            # Record retrieval
            self._client.emit(
                category="tool_call",
                action="rag_retrieval",
                success=True,
                metadata={
                    "results_returned": len(nodes),
                    "duration_ms": duration_ms,
                    "user_id": self._user_id,
                },
            )

            return nodes

        except Exception as e:
            self._client.emit(
                category="tool_call",
                action="rag_retrieval",
                success=False,
                metadata={"error": str(e)[:500], "user_id": self._user_id},
            )
            raise

    def reset_session(self) -> None:
        """Reset session counters."""
        self._retrieval_count = 0
