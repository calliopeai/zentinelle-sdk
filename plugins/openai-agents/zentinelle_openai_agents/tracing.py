"""Export Agents SDK spans to Zentinelle as audit events.

The SDK already instruments a run in detail: agent turns, LLM generations, tool
calls, handoffs and guardrail decisions each open a span. This processor sends
that structure to Zentinelle instead of to OpenAI's trace store, so a deployment
gets the trace without the content leaving the boundary.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Span payloads carry prompts, tool arguments and outputs. The default is to
# record the shape of a run, not its contents: an audit trail that duplicates
# every prompt is a second copy of the data to secure, and a customer who wants
# that copy can ask for it.
DEFAULT_INCLUDE_SPAN_DATA = False

# Fields that are the shape of a run rather than its content.
_STRUCTURAL_FIELDS = (
    "type",
    "name",
    "model",
    "from_agent",
    "to_agent",
    "tools",
    "handoffs",
)


class ZentinelleTracingProcessor:
    """A ``TracingProcessor`` that records spans as Zentinelle events.

    Not a subclass of ``TracingProcessor`` at class-definition time, for the
    same reason as the hooks: subclassing would make the Agents SDK an import
    of this module rather than of the caller. The five methods below are the
    whole interface, and the SDK calls them by name.

    Every method swallows its own errors. These are called synchronously from
    the run, and a tracing exporter that raises would take down the agent it
    was supposed to be watching.
    """

    def __init__(self, client: Any, include_span_data: bool = DEFAULT_INCLUDE_SPAN_DATA):
        self.client = client
        self.include_span_data = include_span_data

    def on_trace_start(self, trace) -> None:
        self._emit(
            "agent_trace_start",
            {
                "trace_id": getattr(trace, "trace_id", None),
                "workflow": getattr(trace, "name", None),
            },
        )

    def on_trace_end(self, trace) -> None:
        self._emit(
            "agent_trace_end",
            {
                "trace_id": getattr(trace, "trace_id", None),
                "workflow": getattr(trace, "name", None),
            },
        )

    def on_span_start(self, span) -> None:
        return None

    def on_span_end(self, span) -> None:
        payload = {
            "trace_id": getattr(span, "trace_id", None),
            "span_id": getattr(span, "span_id", None),
            "parent_id": getattr(span, "parent_id", None),
            "started_at": getattr(span, "started_at", None),
            "ended_at": getattr(span, "ended_at", None),
        }

        data = getattr(span, "span_data", None)
        if data is not None:
            payload["span_type"] = getattr(data, "type", None)
            payload.update(self._span_fields(data))

        error = getattr(span, "error", None)
        if error is not None:
            # An error is always recorded. It is the part of a trace an audit
            # is most likely to be read for, and it is a message rather than
            # user content.
            payload["error"] = getattr(error, "message", None) or str(error)

        self._emit("agent_span", payload)

    def shutdown(self) -> None:
        try:
            self.client.flush_events()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not flush Zentinelle events on shutdown: %s", exc)

    def force_flush(self) -> None:
        self.shutdown()

    def _span_fields(self, data) -> dict:
        if self.include_span_data:
            try:
                exported = data.export()
                if isinstance(exported, dict):
                    return exported
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not export span data: %s", exc)
            return {}

        fields = {}
        for field in _STRUCTURAL_FIELDS:
            value = getattr(data, field, None)
            if value is not None:
                fields[field] = value
        return fields

    def _emit(self, event_type: str, payload: dict) -> None:
        try:
            self.client.emit(
                event_type,
                {k: v for k, v in payload.items() if v is not None},
                category="audit",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record %s: %s", event_type, exc)
