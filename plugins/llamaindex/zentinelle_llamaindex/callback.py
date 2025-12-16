"""
Zentinelle callback handler for LlamaIndex.
"""

import time
from typing import Any, Dict, List, Optional

from llama_index.core.callbacks.base import BaseCallbackHandler
from llama_index.core.callbacks.schema import CBEventType, EventPayload
from zentinelle import ZentinelleClient
from zentinelle.types import ModelUsage

# Maximum age for timing entries before cleanup (5 minutes)
_MAX_TIMING_AGE_SECONDS = 300
# Maximum number of timing entries before forced cleanup
_MAX_TIMING_ENTRIES = 1000


class ZentinelleCallbackHandler(BaseCallbackHandler):
    """
    Callback handler for tracking LlamaIndex operations in Zentinelle.

    Tracks:
    - LLM calls and token usage
    - Embedding operations
    - Retrieval operations
    - Query operations
    - Agent steps

    Example:
        from llama_index.core import Settings
        from zentinelle import ZentinelleClient
        from zentinelle_llamaindex import ZentinelleCallbackHandler

        client = ZentinelleClient(api_key="...", agent_id="...")
        handler = ZentinelleCallbackHandler(client)

        Settings.callback_manager.add_handler(handler)
    """

    def __init__(
        self,
        client: ZentinelleClient,
        track_embeddings: bool = True,
        track_retrieval: bool = True,
        track_llm_inputs: bool = False,
        user_id: Optional[str] = None,
    ):
        """
        Initialize the callback handler.

        Args:
            client: Zentinelle client instance
            track_embeddings: Whether to track embedding operations
            track_retrieval: Whether to track retrieval operations
            track_llm_inputs: Whether to track LLM input content
            user_id: User ID for tracking
        """
        super().__init__(
            event_starts_to_ignore=[],
            event_ends_to_ignore=[],
        )
        self._client = client
        self._track_embeddings = track_embeddings
        self._track_retrieval = track_retrieval
        self._track_llm_inputs = track_llm_inputs
        self._user_id = user_id

        self._event_times: Dict[str, float] = {}
        self._event_data: Dict[str, Dict[str, Any]] = {}
        self._last_cleanup_time = time.time()

    def _cleanup_stale_timings(self) -> None:
        """Remove stale timing entries to prevent memory leaks."""
        now = time.time()

        # Only cleanup if enough time has passed or buffer is too large
        if (now - self._last_cleanup_time < 60 and
                len(self._event_times) < _MAX_TIMING_ENTRIES):
            return

        self._last_cleanup_time = now
        cutoff = now - _MAX_TIMING_AGE_SECONDS

        # Remove entries older than cutoff
        stale_ids = [
            event_id for event_id, start_time in self._event_times.items()
            if start_time < cutoff
        ]
        for event_id in stale_ids:
            del self._event_times[event_id]
            self._event_data.pop(event_id, None)

    def on_event_start(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        parent_id: str = "",
        **kwargs: Any,
    ) -> str:
        """Called when an event starts."""
        self._cleanup_stale_timings()
        self._event_times[event_id] = time.time()
        self._event_data[event_id] = payload or {}

        if event_type == CBEventType.LLM:
            self._on_llm_start(event_id, payload)
        elif event_type == CBEventType.EMBEDDING and self._track_embeddings:
            self._on_embedding_start(event_id, payload)
        elif event_type == CBEventType.RETRIEVE and self._track_retrieval:
            self._on_retrieval_start(event_id, payload)
        elif event_type == CBEventType.QUERY:
            self._on_query_start(event_id, payload)
        elif event_type == CBEventType.AGENT_STEP:
            self._on_agent_step_start(event_id, payload)

        return event_id

    def on_event_end(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        """Called when an event ends."""
        start_time = self._event_times.pop(event_id, None)
        start_data = self._event_data.pop(event_id, {})
        duration_ms = int((time.time() - start_time) * 1000) if start_time else 0

        if event_type == CBEventType.LLM:
            self._on_llm_end(event_id, payload, start_data, duration_ms)
        elif event_type == CBEventType.EMBEDDING and self._track_embeddings:
            self._on_embedding_end(event_id, payload, duration_ms)
        elif event_type == CBEventType.RETRIEVE and self._track_retrieval:
            self._on_retrieval_end(event_id, payload, duration_ms)
        elif event_type == CBEventType.QUERY:
            self._on_query_end(event_id, payload, duration_ms)
        elif event_type == CBEventType.AGENT_STEP:
            self._on_agent_step_end(event_id, payload, duration_ms)

    def _on_llm_start(self, event_id: str, payload: Optional[Dict[str, Any]]) -> None:
        """Handle LLM start event."""
        event_payload: Dict[str, Any] = {"event_id": event_id}

        if self._track_llm_inputs and payload:
            messages = payload.get(EventPayload.MESSAGES, [])
            if messages:
                event_payload["message_count"] = len(messages)

        self._client.emit(
            event_type="llm_start",
            payload=event_payload,
            category="model_request",
            user_id=self._user_id,
        )

    def _on_llm_end(
        self,
        event_id: str,
        payload: Optional[Dict[str, Any]],
        start_data: Dict[str, Any],
        duration_ms: int,
    ) -> None:
        """Handle LLM end event."""
        model = "unknown"
        input_tokens = 0
        output_tokens = 0
        cost = None

        if payload:
            response = payload.get(EventPayload.RESPONSE)
            if response:
                # Extract model and usage from response
                if hasattr(response, "raw"):
                    raw = response.raw
                    model = getattr(raw, "model", "unknown")
                    usage = getattr(raw, "usage", None)
                    if usage:
                        input_tokens = getattr(usage, "prompt_tokens", 0)
                        output_tokens = getattr(usage, "completion_tokens", 0)

        # Track usage for cost policies
        if input_tokens or output_tokens:
            self._client.track_usage(ModelUsage(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
            ))

        self._client.emit(
            event_type="llm_end",
            payload={
                "event_id": event_id,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": duration_ms,
            },
            category="model_request",
            user_id=self._user_id,
        )

    def _on_embedding_start(
        self, event_id: str, payload: Optional[Dict[str, Any]]
    ) -> None:
        """Handle embedding start event."""
        chunks = 0
        if payload:
            chunks = len(payload.get(EventPayload.CHUNKS, []))

        self._client.emit(
            event_type="embedding_start",
            payload={
                "event_id": event_id,
                "chunks": chunks,
            },
            category="tool_call",
            user_id=self._user_id,
        )

    def _on_embedding_end(
        self,
        event_id: str,
        payload: Optional[Dict[str, Any]],
        duration_ms: int,
    ) -> None:
        """Handle embedding end event."""
        self._client.emit(
            event_type="embedding_end",
            payload={
                "event_id": event_id,
                "duration_ms": duration_ms,
            },
            category="tool_call",
            user_id=self._user_id,
        )

    def _on_retrieval_start(
        self, event_id: str, payload: Optional[Dict[str, Any]]
    ) -> None:
        """Handle retrieval start event."""
        query = ""
        if payload:
            query_bundle = payload.get(EventPayload.QUERY_STR, "")
            query = str(query_bundle)[:200]

        self._client.emit(
            event_type="retrieval_start",
            payload={
                "event_id": event_id,
                "query_preview": query,
            },
            category="tool_call",
            user_id=self._user_id,
        )

    def _on_retrieval_end(
        self,
        event_id: str,
        payload: Optional[Dict[str, Any]],
        duration_ms: int,
    ) -> None:
        """Handle retrieval end event."""
        node_count = 0
        if payload:
            nodes = payload.get(EventPayload.NODES, [])
            node_count = len(nodes)

        self._client.emit(
            event_type="retrieval_end",
            payload={
                "event_id": event_id,
                "duration_ms": duration_ms,
                "node_count": node_count,
            },
            category="tool_call",
            user_id=self._user_id,
        )

    def _on_query_start(
        self, event_id: str, payload: Optional[Dict[str, Any]]
    ) -> None:
        """Handle query start event."""
        query = ""
        if payload:
            query = str(payload.get(EventPayload.QUERY_STR, ""))[:200]

        self._client.emit(
            event_type="query_start",
            payload={
                "event_id": event_id,
                "query_preview": query,
            },
            category="model_request",
            user_id=self._user_id,
        )

    def _on_query_end(
        self,
        event_id: str,
        payload: Optional[Dict[str, Any]],
        duration_ms: int,
    ) -> None:
        """Handle query end event."""
        response_length = 0
        if payload:
            response = payload.get(EventPayload.RESPONSE)
            if response:
                response_length = len(str(response))

        self._client.emit(
            event_type="query_end",
            payload={
                "event_id": event_id,
                "duration_ms": duration_ms,
                "response_length": response_length,
            },
            category="model_request",
            user_id=self._user_id,
        )

    def _on_agent_step_start(
        self, event_id: str, payload: Optional[Dict[str, Any]]
    ) -> None:
        """Handle agent step start event."""
        self._client.emit(
            event_type="agent_step_start",
            payload={
                "event_id": event_id,
            },
            category="task_execution",
            user_id=self._user_id,
        )

    def _on_agent_step_end(
        self,
        event_id: str,
        payload: Optional[Dict[str, Any]],
        duration_ms: int,
    ) -> None:
        """Handle agent step end event."""
        self._client.emit(
            event_type="agent_step_end",
            payload={
                "event_id": event_id,
                "duration_ms": duration_ms,
            },
            category="task_execution",
            user_id=self._user_id,
        )

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        """Start a trace."""
        pass

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """End a trace."""
        pass
