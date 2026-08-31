"""Zentinelle governance for Agno agents.

Agno has three hook points and all three can refuse:

- ``pre_hooks`` run before the model is called, and raising ``InputCheckError``
  stops the run. Agno catches everything else a hook raises and logs it, so
  that specific exception is the difference between a refusal and a warning
  nobody sees.
- ``post_hooks`` run on the output; ``OutputCheckError`` is the matching one.
- ``tool_hooks`` are middleware around a tool call. The hook is handed the
  function it wraps and decides whether to call it, so a refusal is simply not
  calling it.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

AGENT_TYPE = "agno"

_CONTENT_LIMIT = 4000


def _summarise(value: Any, limit: int = _CONTENT_LIMIT) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    for attr in ("input_content", "content", "text", "message"):
        inner = getattr(value, attr, None)
        if isinstance(inner, str):
            return inner[:limit]
    return str(value)[:limit]


class ZentinelleGuard:
    """Builds the three hooks an Agno agent needs.

    One object so the hooks share a client and settings:

        guard = ZentinelleGuard(client)
        agent = Agent(
            model=...,
            pre_hooks=[guard.pre_hook],
            post_hooks=[guard.post_hook],
            tool_hooks=[guard.tool_hook],
        )

    Agno inspects each hook's signature and passes only the arguments it
    declares, which is why these take the exact parameter names below. Renaming
    them silently stops the value arriving.
    """

    def __init__(
        self,
        client: Any,
        user_id: Optional[str] = None,
        evaluate_input: bool = True,
        evaluate_output: bool = True,
        evaluate_tool_calls: bool = True,
        track_token_usage: bool = True,
        fail_open: bool = False,
    ):
        self.client = client
        self.user_id = user_id
        self.evaluate_input = evaluate_input
        self.evaluate_output = evaluate_output
        self.evaluate_tool_calls = evaluate_tool_calls
        self.track_token_usage = track_token_usage
        self.fail_open = fail_open

    # -- input ------------------------------------------------------------

    def pre_hook(self, run_input) -> None:
        """Refuse a disallowed request before the model is called."""
        if not self.evaluate_input:
            return

        from agno.exceptions import InputCheckError

        result = self._evaluate(
            "model_request",
            {"direction": "input", "harness": AGENT_TYPE,
             "content": _summarise(run_input)},
            InputCheckError,
        )
        if result is not None and not result.allowed:
            raise InputCheckError(
                f"Refused by Zentinelle policy: {result.reason or 'no reason given'}"
            )

    # -- output -----------------------------------------------------------

    def post_hook(self, run_output) -> None:
        """Refuse a disallowed output, and record what the run cost."""
        if self.track_token_usage:
            self._track(run_output)

        if not self.evaluate_output:
            return

        from agno.exceptions import OutputCheckError

        result = self._evaluate(
            "model_response",
            {"direction": "output", "harness": AGENT_TYPE,
             "content": _summarise(run_output)},
            OutputCheckError,
        )
        if result is not None and not result.allowed:
            raise OutputCheckError(
                f"Refused by Zentinelle policy: {result.reason or 'no reason given'}"
            )

    # -- tools ------------------------------------------------------------

    def tool_hook(self, function_name, func, arguments):
        """Middleware around a tool call: check, then call or refuse.

        A refusal raises rather than returning an explanatory string to the
        model. Returning the refusal as the tool's result lets the agent decide
        what to do about its own governance, which in practice means trying a
        different route to the same action.
        """
        if not self.evaluate_tool_calls:
            return func(**arguments)

        try:
            result = self.client.can_call_tool(function_name, self.user_id)
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning(
                    "Tool check failed, allowing %s: %s", function_name, exc
                )
                return func(**arguments)
            raise PolicyViolationError(
                f"Policy check for tool '{function_name}' failed and fail_open "
                f"is off: {exc}"
            ) from exc

        if not result.allowed:
            raise PolicyViolationError(
                f"Tool '{function_name}' was refused by policy: "
                f"{result.reason or 'no reason given'}",
                result,
            )

        output = func(**arguments)
        try:
            self.client.emit_tool_call(tool_name=function_name, user_id=self.user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record tool call: %s", exc)
        return output

    # -- shared -----------------------------------------------------------

    def _evaluate(self, action: str, context: dict, check_error):
        try:
            return self.client.evaluate(action, self.user_id, context)
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Zentinelle check failed, allowing: %s", exc)
                return None
            # Agno swallows every hook exception except its own check errors,
            # so a plain raise here would be logged and the run would continue
            # ungoverned. Raising the check error is what actually stops it.
            raise check_error(
                f"Zentinelle policy check failed and fail_open is off: {exc}"
            ) from exc

    def _track(self, run_output) -> None:
        metrics = getattr(run_output, "metrics", None)
        if metrics is None:
            return
        try:
            from zentinelle import ModelUsage

            self.client.track_usage(
                ModelUsage(
                    provider="openai",
                    model=getattr(run_output, "model", None) or "unknown",
                    input_tokens=getattr(metrics, "input_tokens", 0) or 0,
                    output_tokens=getattr(metrics, "output_tokens", 0) or 0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record model usage: %s", exc)


class PolicyViolationError(Exception):
    """A tool call was refused by policy."""

    def __init__(self, message: str, result: Any = None):
        super().__init__(message)
        self.result = result
