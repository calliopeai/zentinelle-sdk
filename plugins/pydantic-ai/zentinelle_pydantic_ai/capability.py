"""Zentinelle governance as a Pydantic AI capability.

Pydantic AI has the cleanest enforcement surface of any harness here. Its
capability hooks are not advisory: `before_model_request` and
`before_tool_execute` are awaited on the path to the thing they precede, so
raising from one stops it. Nothing has to be wrapped, subclassed or
monkey-patched.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from pydantic_ai.capabilities import AbstractCapability

logger = logging.getLogger(__name__)

AGENT_TYPE = "pydantic_ai"

# The conversation is not sent whole on every check: a long run would post its
# entire history each time, and content policies match on the current turn.
_CONTENT_LIMIT = 4000


class PolicyViolationError(Exception):
    """A request or tool call was refused by policy.

    Raised from a hook, which aborts the run. The alternative Pydantic AI
    offers is `SkipModelRequest` / `SkipToolExecution`, which substitute a
    result and let the agent carry on. That is the right shape for a fallback
    and the wrong one for a refusal: handing the denial back as a tool result
    lets the model decide what to do about its own governance, and in practice
    it tries another route to the same action. Use `on_denial="substitute"` if
    a soft refusal is genuinely what you want.
    """

    def __init__(self, message: str, result: Any = None):
        super().__init__(message)
        self.result = result


def _summarise(value: Any, limit: int = _CONTENT_LIMIT) -> str:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, (list, tuple)):
        parts = []
        for item in list(value)[-4:]:
            content = getattr(item, "content", None)
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(item, str):
                parts.append(item)
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)[:limit]
    return str(value)[:limit]


class ZentinelleCapability(AbstractCapability):
    """Policy enforcement, token accounting and audit for a Pydantic AI agent.

    Register it with `Agent(..., capabilities=[ZentinelleCapability(client)])`.
    """

    def __init__(
        self,
        client: Any,
        user_id: Optional[str] = None,
        evaluate_requests: bool = True,
        evaluate_tool_calls: bool = True,
        track_token_usage: bool = True,
        fail_open: bool = False,
        on_denial: str = "raise",
    ):
        if on_denial not in ("raise", "substitute"):
            raise ValueError("on_denial must be 'raise' or 'substitute'")
        self.client = client
        self.user_id = user_id
        self.evaluate_requests = evaluate_requests
        self.evaluate_tool_calls = evaluate_tool_calls
        self.track_token_usage = track_token_usage
        self.fail_open = fail_open
        self.on_denial = on_denial

    # -- policy -----------------------------------------------------------

    async def _evaluate(self, action: str, context: dict):
        """Ask Zentinelle, off the event loop.

        The client is synchronous `requests`. Awaiting it directly would block
        the loop the agent runs on, and with it every other request in the
        process.
        """
        try:
            return await asyncio.to_thread(
                self.client.evaluate, action, self.user_id, context
            )
        except Exception as exc:  # noqa: BLE001 - the decision is what follows
            if self.fail_open:
                logger.warning("Zentinelle check failed, allowing: %s", exc)
                return None
            raise PolicyViolationError(
                f"Zentinelle policy check failed and fail_open is off: {exc}"
            ) from exc

    # -- model requests ---------------------------------------------------

    async def before_model_request(self, ctx, request_context):
        if not self.evaluate_requests:
            return request_context

        result = await self._evaluate(
            "model_request",
            {
                "direction": "input",
                "harness": AGENT_TYPE,
                "content": _summarise(getattr(request_context, "messages", None)),
            },
        )
        if result is None or result.allowed:
            return request_context

        reason = result.reason or "no reason given"
        if self.on_denial == "substitute":
            from pydantic_ai import SkipModelRequest
            from pydantic_ai.messages import ModelResponse, TextPart

            raise SkipModelRequest(
                ModelResponse(parts=[TextPart(content=f"Refused by policy: {reason}")])
            )

        raise PolicyViolationError(f"Request refused by policy: {reason}", result)

    async def after_model_request(self, ctx, *, request_context, response):
        if self.track_token_usage:
            self._track(response)
        return response

    def _track(self, response) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        try:
            from zentinelle import ModelUsage

            self.client.track_usage(
                ModelUsage(
                    provider="openai",
                    model=getattr(response, "model_name", None) or "unknown",
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            # Telemetry is best-effort. An agent must not fail because a usage
            # buffer refused an append.
            logger.warning("Could not record model usage: %s", exc)

    # -- tool calls -------------------------------------------------------

    async def before_tool_execute(self, ctx, *, call, tool_def, args):
        if not self.evaluate_tool_calls:
            return args

        name = getattr(tool_def, "name", None) or getattr(call, "tool_name", "unknown")
        try:
            result = await asyncio.to_thread(
                self.client.can_call_tool, name, self.user_id
            )
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Tool check failed, allowing %s: %s", name, exc)
                return args
            raise PolicyViolationError(
                f"Policy check for tool '{name}' failed and fail_open is off: {exc}"
            ) from exc

        if result.allowed:
            return args

        reason = result.reason or "no reason given"
        if self.on_denial == "substitute":
            from pydantic_ai import SkipToolExecution

            raise SkipToolExecution(f"Refused by policy: {reason}")

        raise PolicyViolationError(
            f"Tool '{name}' was refused by policy: {reason}", result
        )

    async def after_tool_execute(self, ctx, *, call, tool_def, args, result):
        name = getattr(tool_def, "name", None) or getattr(call, "tool_name", "unknown")
        try:
            self.client.emit_tool_call(tool_name=name, user_id=self.user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record tool call: %s", exc)
        return result
