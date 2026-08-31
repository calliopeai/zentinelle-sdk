"""Zentinelle governance for DSPy.

DSPy has a callback system, `BaseCallback`, with `on_lm_start` and
`on_tool_start` hooks that look like the obvious place for this. They are not,
and the reason is worth stating because it is invisible from the signatures:
DSPy's dispatcher wraps every callback invocation in its own `try/except`, logs
the exception, and then calls the wrapped function anyway. A governance
callback that raised would print a warning and let the call through.

So enforcement wraps instead:

- `ZentinelleLM` subclasses `dspy.LM` and checks in `forward`, before litellm.
- `governed_tool` wraps a `dspy.Tool`'s function, before it runs.

`ZentinelleCallback` is offered for audit, and is audit only. It is built on
the same dispatcher that swallows exceptions, so it cannot refuse anything.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from dspy.clients.lm import LM

logger = logging.getLogger(__name__)

AGENT_TYPE = "dspy"

_CONTENT_LIMIT = 4000


class PolicyViolationError(Exception):
    """A request or tool call was refused by policy."""

    def __init__(self, message: str, result: Any = None):
        super().__init__(message)
        self.result = result


def _summarise(prompt, messages, limit: int = _CONTENT_LIMIT) -> str:
    if isinstance(prompt, str) and prompt:
        return prompt[:limit]
    parts = []
    for message in list(messages or [])[-4:]:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            parts.append(content)
        elif content is not None:
            parts.append(str(content))
    return "\n".join(parts)[:limit]


class ZentinelleLM(LM):
    """A `dspy.LM` that asks Zentinelle before it asks the provider.

        lm = ZentinelleLM(client, "openai/gpt-5", api_base=..., api_key=...)
        dspy.configure(lm=lm)

    Subclasses `LM` rather than wrapping one, because DSPy passes the LM
    through settings and adapters that read its attributes directly; a proxy
    object would have to reproduce all of them.
    """

    def __init__(
        self,
        client: Any,
        model: str,
        user_id: Optional[str] = None,
        evaluate_requests: bool = True,
        track_token_usage: bool = True,
        fail_open: bool = False,
        **lm_kwargs: Any,
    ):
        super().__init__(model, **lm_kwargs)
        self.zentinelle = client
        self.user_id = user_id
        self.evaluate_requests = evaluate_requests
        self.track_token_usage = track_token_usage
        self.fail_open = fail_open

    def forward(self, prompt=None, messages=None, **kwargs):
        if self.evaluate_requests:
            self._check(prompt, messages)

        response = super().forward(prompt=prompt, messages=messages, **kwargs)

        if self.track_token_usage:
            self._track(response)
        return response

    def _check(self, prompt, messages) -> None:
        try:
            result = self.zentinelle.evaluate(
                "model_request",
                self.user_id,
                {
                    "direction": "input",
                    "harness": AGENT_TYPE,
                    "content": _summarise(prompt, messages),
                },
            )
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Zentinelle check failed, allowing: %s", exc)
                return
            raise PolicyViolationError(
                f"Zentinelle policy check failed and fail_open is off: {exc}"
            ) from exc

        if not result.allowed:
            raise PolicyViolationError(
                f"Request refused by policy: {result.reason or 'no reason given'}",
                result,
            )

    def _track(self, response) -> None:
        usage = getattr(response, "usage", None) or {}
        if not isinstance(usage, dict):
            usage = dict(getattr(usage, "__dict__", {}) or {})
        if not usage:
            return
        try:
            from zentinelle import ModelUsage

            self.zentinelle.track_usage(
                ModelUsage(
                    provider="openai",
                    model=self.model,
                    # litellm's response passes the provider's own names
                    # through; DSPy does not normalise them.
                    input_tokens=usage.get("prompt_tokens")
                    or usage.get("input_tokens")
                    or 0,
                    output_tokens=usage.get("completion_tokens")
                    or usage.get("output_tokens")
                    or 0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record model usage: %s", exc)


def governed_tool(
    tool,
    client: Any,
    user_id: Optional[str] = None,
    fail_open: bool = False,
):
    """Wrap a `dspy.Tool` so a refused call never reaches its function.

    `Tool.__call__` is decorated with DSPy's `@with_callbacks` and then calls
    `self.func(**parsed_kwargs)`. Wrapping `func` puts the check inside that,
    after argument validation and before the work, and does not depend on the
    callback dispatcher that swallows exceptions.
    """
    if getattr(tool, "_zentinelle_governed", False):
        return tool

    original_func = tool.func

    def func(**kwargs):
        name = getattr(tool, "name", None) or "unknown"
        try:
            result = client.can_call_tool(name, user_id)
        except Exception as exc:  # noqa: BLE001
            if fail_open:
                logger.warning("Tool check failed, allowing %s: %s", name, exc)
                return original_func(**kwargs)
            raise PolicyViolationError(
                f"Policy check for tool '{name}' failed and fail_open is off: {exc}"
            ) from exc

        if not result.allowed:
            raise PolicyViolationError(
                f"Tool '{name}' was refused by policy: "
                f"{result.reason or 'no reason given'}",
                result,
            )

        output = original_func(**kwargs)
        try:
            client.emit_tool_call(tool_name=name, user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record tool call: %s", exc)
        return output

    tool.func = func
    tool._zentinelle_governed = True
    return tool


def govern_tools(tools, client: Any, user_id: Optional[str] = None,
                 fail_open: bool = False):
    """`governed_tool` over a list."""
    return [governed_tool(t, client, user_id, fail_open) for t in tools]
