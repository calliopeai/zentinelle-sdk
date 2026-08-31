"""Run lifecycle hooks: tool governance and token accounting.

Guardrails cover what goes into a run and what comes out of it. They do not see
the tool calls in between, which is where an agent does the things that have
consequences outside the conversation. ``RunHooks`` does see them, and a hook
that raises stops the run, so a denied tool call does not execute.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PolicyViolationError(Exception):
    """A tool call was refused by policy.

    Raised from a lifecycle hook, which aborts the run. That is deliberately
    loud: the alternative is returning an error string to the model, which lets
    the agent decide what to do about its own governance and, in practice,
    try a different route to the same action.
    """

    def __init__(self, message: str, result: Any = None):
        super().__init__(message)
        self.result = result


def _tool_name(tool: Any, context: Any) -> str:
    for source, attr in ((context, "tool_name"), (tool, "name")):
        value = getattr(source, attr, None)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def _model_name(agent: Any) -> str:
    model = getattr(agent, "model", None)
    if isinstance(model, str) and model:
        return model
    # A Model instance rather than a name: its own `model` attribute usually
    # carries the string, and if it does not, an honest "unknown" beats a
    # repr in the usage record.
    inner = getattr(model, "model", None)
    return inner if isinstance(inner, str) and inner else "unknown"


class ZentinelleRunHooks:
    """Governance hooks for ``Runner.run(..., hooks=...)``.

    Not a subclass of ``RunHooks`` at class-definition time: importing the
    Agents SDK at module import would make it a hard dependency of the package,
    and the base class only declares no-op coroutines that this class overrides
    in full. It satisfies the same interface, which is what the runner awaits.
    """

    def __init__(
        self,
        client: Any,
        user_id: Optional[str] = None,
        evaluate_tool_calls: bool = True,
        track_token_usage: bool = True,
        fail_open: bool = False,
    ):
        self.client = client
        self.user_id = user_id
        self.evaluate_tool_calls = evaluate_tool_calls
        self.track_token_usage = track_token_usage
        self.fail_open = fail_open
        self._tool_started_at: dict[int, float] = {}

    # -- tool governance --------------------------------------------------

    async def on_tool_start(self, context, agent, tool) -> None:
        name = _tool_name(tool, context)
        self._tool_started_at[id(context)] = time.monotonic()

        if not self.evaluate_tool_calls:
            return

        try:
            # Off the loop: the client is synchronous, and blocking here stalls
            # every other coroutine in the process, not just this run.
            result = await asyncio.to_thread(
                self.client.can_call_tool, name, self.user_id
            )
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Tool policy check failed, allowing %s: %s", name, exc)
                return
            raise PolicyViolationError(
                f"Policy check for tool '{name}' failed and fail_open is off: {exc}"
            ) from exc

        if not result.allowed:
            raise PolicyViolationError(
                f"Tool '{name}' was refused by policy: {result.reason or 'no reason given'}",
                result,
            )

    async def on_tool_end(self, context, agent, tool, result) -> None:
        started = self._tool_started_at.pop(id(context), None)
        duration_ms = int((time.monotonic() - started) * 1000) if started else None
        try:
            self.client.emit_tool_call(
                tool_name=_tool_name(tool, context),
                user_id=self.user_id,
                duration_ms=duration_ms,
            )
        except Exception as exc:  # noqa: BLE001
            # Audit is buffered and best-effort. Failing the run because a
            # telemetry buffer refused an append would turn an observability
            # problem into an outage.
            logger.warning("Could not record tool call: %s", exc)

    # -- token accounting -------------------------------------------------

    async def on_llm_end(self, context, agent, response) -> None:
        if not self.track_token_usage:
            return

        usage = getattr(response, "usage", None)
        if usage is None:
            return

        try:
            from zentinelle import ModelUsage

            self.client.track_usage(
                ModelUsage(
                    provider="openai",
                    model=_model_name(agent),
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record model usage: %s", exc)

    # -- run shape --------------------------------------------------------

    async def on_agent_start(self, context, agent) -> None:
        self._emit("agent_start", {"agent": getattr(agent, "name", "unknown")})

    async def on_agent_end(self, context, agent, output) -> None:
        self._emit("agent_end", {"agent": getattr(agent, "name", "unknown")})

    async def on_handoff(self, context, from_agent, to_agent) -> None:
        # Worth recording on its own: a handoff moves the run to an agent with
        # different tools and a different prompt, so "which agent did this"
        # cannot be answered from the tool events alone.
        self._emit(
            "agent_handoff",
            {
                "from": getattr(from_agent, "name", "unknown"),
                "to": getattr(to_agent, "name", "unknown"),
            },
        )

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        return None

    def _emit(self, event_type: str, payload: dict) -> None:
        try:
            self.client.emit(event_type, {**payload, "harness": "openai_agents"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record %s: %s", event_type, exc)
