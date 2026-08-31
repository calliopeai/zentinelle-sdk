"""Zentinelle governance for the BeeAI Framework (IBM's Bee Agent Framework).

BeeAI's emitter is one of the few event systems here that can actually refuse
something. `Emitter._invoke` wraps a listener's exception as an `EmitterError`
and re-raises it inside an `asyncio.TaskGroup`, so it propagates out of
`emit()` rather than being logged and dropped. And the `"start"` event for both
chat models and tools is emitted *before* the work: for a tool,
`emit("start", ...)` runs ahead of `self._run(...)`; for a chat model, ahead of
the retryable that calls the provider.

So a listener that raises on `"start"` stops the call. That is the whole
mechanism here.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

AGENT_TYPE = "bee_agent"

_CONTENT_LIMIT = 4000


class PolicyViolationError(Exception):
    """A request or tool call was refused by policy."""

    def __init__(self, message: str, result: Any = None):
        super().__init__(message)
        self.result = result


def _summarise(value: Any, limit: int = _CONTENT_LIMIT) -> str:
    """Text from a ChatModelStartEvent's input, as far as one is reachable."""
    messages = getattr(value, "input", None) or getattr(value, "messages", None)
    parts = []
    for message in list(messages or [])[-4:]:
        text = getattr(message, "text", None)
        if isinstance(text, str) and text:
            parts.append(text)
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            parts.append(content)
        elif content is not None:
            parts.append(str(content))
    if parts:
        return "\n".join(parts)[:limit]
    return str(value)[:limit] if value is not None else ""


class ZentinelleGuard:
    """Builds the emitter listeners that govern a BeeAI run.

        guard = ZentinelleGuard(client)
        guard.attach_model(llm)
        for tool in tools:
            guard.attach_tool(tool)

    Or, for everything a single agent does:

        guard.attach_agent(agent)

    `attach_agent` subscribes on the agent's own emitter, which child emitters
    pipe into. That covers agents like `ReActAgent` and `ToolCallingAgent`,
    which have no middleware constructor argument at all.
    """

    def __init__(
        self,
        client: Any,
        user_id: Optional[str] = None,
        evaluate_requests: bool = True,
        evaluate_tool_calls: bool = True,
        track_token_usage: bool = True,
        fail_open: bool = False,
    ):
        self.client = client
        self.user_id = user_id
        self.evaluate_requests = evaluate_requests
        self.evaluate_tool_calls = evaluate_tool_calls
        self.track_token_usage = track_token_usage
        self.fail_open = fail_open

    # -- subscription -----------------------------------------------------

    def attach_model(self, chat_model) -> None:
        """Govern a `ChatModel`'s calls."""
        chat_model.emitter.on("start", self.on_model_start)
        if self.track_token_usage:
            chat_model.emitter.on("success", self.on_model_success)

    def attach_tool(self, tool) -> None:
        """Govern a `Tool`'s invocations."""
        tool.emitter.on("start", self.on_tool_start)

    def attach_agent(self, agent) -> None:
        """Govern everything under one agent.

        Child emitters pipe into the agent's, so a single subscription here
        sees the model and tool events from the whole run. Matched on the event
        path rather than the bare name, because at this level both a model and
        a tool emit `"start"`.
        """
        agent.emitter.on("*.*", self._on_any)

    # -- listeners --------------------------------------------------------

    async def _on_any(self, data: Any, event) -> None:
        name = getattr(event, "name", None)
        path = getattr(event, "path", "") or ""
        if name != "start":
            if name == "success" and ".chat." in path and self.track_token_usage:
                await self.on_model_success(data, event)
            return
        if ".chat." in path or "backend" in path:
            await self.on_model_start(data, event)
        else:
            await self.on_tool_start(data, event)

    async def on_model_start(self, data: Any, event=None) -> None:
        if not self.evaluate_requests:
            return

        result = self._evaluate(
            "model_request",
            {
                "direction": "input",
                "harness": AGENT_TYPE,
                "content": _summarise(data),
            },
        )
        if result is None:
            return
        if not result.allowed:
            raise PolicyViolationError(
                f"Request refused by policy: {result.reason or 'no reason given'}",
                result,
            )

    async def on_tool_start(self, data: Any, event=None) -> None:
        if not self.evaluate_tool_calls:
            return

        name = self._tool_name(data, event)
        try:
            result = self.client.can_call_tool(name, self.user_id)
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Tool check failed, allowing %s: %s", name, exc)
                return
            raise PolicyViolationError(
                f"Policy check for tool '{name}' failed and fail_open is off: {exc}"
            ) from exc

        if not result.allowed:
            raise PolicyViolationError(
                f"Tool '{name}' was refused by policy: "
                f"{result.reason or 'no reason given'}",
                result,
            )

        try:
            self.client.emit_tool_call(tool_name=name, user_id=self.user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record tool call: %s", exc)

    async def on_model_success(self, data: Any, event=None) -> None:
        output = getattr(data, "value", None)
        usage = getattr(output, "usage", None)
        if usage is None:
            return
        try:
            from zentinelle import ModelUsage

            self.client.track_usage(
                ModelUsage(
                    provider="openai",
                    model=getattr(output, "model", None) or "unknown",
                    input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record model usage: %s", exc)

    # -- helpers ----------------------------------------------------------

    def _tool_name(self, data: Any, event) -> str:
        creator = getattr(event, "creator", None)
        for candidate in (getattr(creator, "name", None), getattr(data, "name", None)):
            if isinstance(candidate, str) and candidate:
                return candidate
        path = getattr(event, "path", "") or ""
        # Event paths look like "tool.<name>.start"; the middle segment is the
        # tool when nothing better is available.
        segments = [s for s in path.split(".") if s]
        if len(segments) >= 3:
            return segments[-2]
        return "unknown"

    def _evaluate(self, action: str, context: dict):
        try:
            return self.client.evaluate(action, self.user_id, context)
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Zentinelle check failed, allowing: %s", exc)
                return None
            raise PolicyViolationError(
                f"Zentinelle policy check failed and fail_open is off: {exc}"
            ) from exc
