"""Zentinelle governance as a Google ADK plugin.

ADK has two callback layers: per-agent callbacks on `LlmAgent`, and plugin
callbacks on `BasePlugin` registered with the `Runner`. This uses the plugin
layer, for two reasons. It applies to every agent the runner drives, including
sub-agents a multi-agent app creates at runtime, so governance cannot be
skipped by adding an agent. And plugin callbacks take precedence over agent
callbacks, so an agent cannot register its own callback that pre-empts this
one.

The short-circuit contract is uniform in ADK: return non-None from a `before_*`
callback and the thing it precedes does not happen, with the returned value
used as the result. So a denial here is a returned refusal rather than a raised
exception. That is ADK's design, not a choice made here.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from google.adk.plugins import BasePlugin

logger = logging.getLogger(__name__)

AGENT_TYPE = "google_adk"

_CONTENT_LIMIT = 4000


def _text_of(content) -> str:
    """The text of a `types.Content`, as far as one exists."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content[:_CONTENT_LIMIT]
    parts = getattr(content, "parts", None) or []
    texts = [getattr(p, "text", None) for p in parts]
    return "\n".join(t for t in texts if t)[:_CONTENT_LIMIT]


def _refusal(reason: str):
    """An `LlmResponse` that says why, in place of the model's answer."""
    from google.adk.models import LlmResponse
    from google.genai import types

    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text=f"Refused by Zentinelle policy: {reason}")],
        )
    )


class ZentinellePlugin(BasePlugin):
    """Policy enforcement, token accounting and audit for an ADK runner.

        runner = Runner(
            agent=agent,
            plugins=[ZentinellePlugin(client)],
            ...
        )
    """

    def __init__(
        self,
        client: Any,
        name: str = "zentinelle",
        user_id: Optional[str] = None,
        evaluate_requests: bool = True,
        evaluate_tool_calls: bool = True,
        track_token_usage: bool = True,
        fail_open: bool = False,
    ):
        super().__init__(name=name)
        self.client = client
        self.user_id = user_id
        self.evaluate_requests = evaluate_requests
        self.evaluate_tool_calls = evaluate_tool_calls
        self.track_token_usage = track_token_usage
        self.fail_open = fail_open

    # -- model requests ---------------------------------------------------

    async def before_model_callback(self, *, callback_context, llm_request):
        """Return None to proceed; an LlmResponse to stop before the model."""
        if not self.evaluate_requests:
            return None

        result = self._evaluate(
            "model_request",
            {
                "direction": "input",
                "harness": AGENT_TYPE,
                "agent": getattr(callback_context, "agent_name", None) or "unknown",
                "content": "\n".join(
                    _text_of(c) for c in (getattr(llm_request, "contents", None) or [])[-4:]
                ),
            },
        )
        if result is None or result.allowed:
            return None
        return _refusal(result.reason or "no reason given")

    async def after_model_callback(self, *, callback_context, llm_response):
        if self.track_token_usage:
            self._track(llm_response)
        # None keeps the model's own response. Returning one here would
        # replace it.
        return None

    def _track(self, llm_response) -> None:
        usage = getattr(llm_response, "usage_metadata", None)
        if usage is None:
            return
        try:
            from zentinelle import ModelUsage

            self.client.track_usage(
                ModelUsage(
                    provider="google",
                    model=getattr(llm_response, "model", None) or "unknown",
                    # Gemini's names for the same two counts.
                    input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record model usage: %s", exc)

    # -- tool calls -------------------------------------------------------

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        """Return None to proceed; a dict to stop before the tool runs."""
        if not self.evaluate_tool_calls:
            return None

        name = getattr(tool, "name", None) or "unknown"
        try:
            result = self.client.can_call_tool(name, self.user_id)
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Tool check failed, allowing %s: %s", name, exc)
                return None
            return {
                "error": f"Policy check for tool '{name}' failed and fail_open "
                f"is off: {exc}"
            }

        if result.allowed:
            return None
        return {
            "error": f"Tool '{name}' was refused by Zentinelle policy: "
            f"{result.reason or 'no reason given'}"
        }

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
        try:
            self.client.emit_tool_call(
                tool_name=getattr(tool, "name", None) or "unknown",
                user_id=self.user_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record tool call: %s", exc)
        return None

    # -- shared -----------------------------------------------------------

    def _evaluate(self, action: str, context: dict):
        try:
            return self.client.evaluate(action, self.user_id, context)
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Zentinelle check failed, allowing: %s", exc)
                return None
            # No exception: raising from an ADK callback aborts the runner
            # rather than producing a refusal the caller can read. A refusal
            # response is both the framework's contract and the more useful
            # answer.
            return _DeniedResult(
                f"Zentinelle policy check failed and fail_open is off: {exc}"
            )


class _DeniedResult:
    """A refusal shaped like an `EvaluateResult`, for the fail-closed path."""

    allowed = False

    def __init__(self, reason: str):
        self.reason = reason
