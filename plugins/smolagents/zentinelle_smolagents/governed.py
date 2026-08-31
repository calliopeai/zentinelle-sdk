"""Zentinelle governance for smolagents.

smolagents has no pre-execution hook. `step_callbacks` fires in
`_finalize_step`, after the model has answered and the tool has run, so it can
record a run but cannot change one. `final_answer_checks` gates only the final
answer.

So enforcement here is by wrapping, in two places:

- `ZentinelleModel` wraps a `Model` and checks before `generate` reaches the
  provider.
- `governed_tool` wraps a `Tool` and checks inside `__call__`, before `forward`
  runs.

The tool wrapper is the one that matters for `CodeAgent`. A `ToolCallingAgent`
routes every call through `execute_tool_call`, so one override would do; a
`CodeAgent` does not call tools itself at all — the model writes Python and the
executor runs it with the tool objects in its namespace. There is no per-call
choke point in the agent for that, which is why governance goes on the tool.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from smolagents.models import Model

logger = logging.getLogger(__name__)

AGENT_TYPE = "smolagents"

_CONTENT_LIMIT = 4000


class PolicyViolationError(Exception):
    """A request or tool call was refused by policy."""

    def __init__(self, message: str, result: Any = None):
        super().__init__(message)
        self.result = result


def _summarise(messages, limit: int = _CONTENT_LIMIT) -> str:
    parts = []
    for message in list(messages or [])[-4:]:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for chunk in content:
                text = chunk.get("text") if isinstance(chunk, dict) else None
                if text:
                    parts.append(text)
    return "\n".join(parts)[:limit]


class ZentinelleModel(Model):
    """A `Model` that asks Zentinelle before it asks the provider.

    Wraps rather than subclasses a concrete model, so it works with any of
    them: `OpenAIModel`, `LiteLLMModel`, `InferenceClientModel` or one of your
    own.
    """

    def __init__(
        self,
        model: Model,
        client: Any,
        user_id: Optional[str] = None,
        evaluate_requests: bool = True,
        track_token_usage: bool = True,
        fail_open: bool = False,
    ):
        # Not calling super().__init__: the base sets up state for a model that
        # talks to a provider, and this one delegates all of that to `model`.
        self.model = model
        self.client = client
        self.user_id = user_id
        self.evaluate_requests = evaluate_requests
        self.track_token_usage = track_token_usage
        self.fail_open = fail_open

    @property
    def model_id(self) -> str:
        return getattr(self.model, "model_id", "unknown")

    def generate(self, messages, **kwargs):
        if self.evaluate_requests:
            self._check(messages)

        message = self.model.generate(messages, **kwargs)

        if self.track_token_usage:
            self._track(message)
        return message

    def __call__(self, *args, **kwargs):
        return self.generate(*args, **kwargs)

    def __getattr__(self, name):
        # Anything not governed here belongs to the wrapped model. Defined
        # explicitly because a smolagents model carries provider-specific
        # attributes that agents read directly.
        return getattr(self.__dict__["model"], name)

    def _check(self, messages) -> None:
        try:
            result = self.client.evaluate(
                "model_request",
                self.user_id,
                {
                    "direction": "input",
                    "harness": AGENT_TYPE,
                    "content": _summarise(messages),
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

    def _track(self, message) -> None:
        usage = getattr(message, "token_usage", None)
        if usage is None:
            return
        try:
            from zentinelle import ModelUsage

            self.client.track_usage(
                ModelUsage(
                    provider="openai",
                    model=self.model_id,
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0,
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
    """Wrap a tool so a refused call never reaches its `forward`.

    The tool object is modified in place and returned. Replacing it with a
    proxy would break `CodeAgent`, which puts the tool into the executor's
    namespace and relies on it being the thing the model was told about.

    `forward` is what gets wrapped, not `__call__`. Assigning `__call__` on an
    instance does nothing useful: Python looks up dunder methods on the type,
    so `tool(...)` would still reach the original and the tool would be
    ungoverned while appearing wrapped. `forward` is an ordinary attribute, so
    instance assignment takes effect, and `Tool.__call__` calls
    `self.forward(...)` after its setup, which also keeps input sanitisation
    working.
    """
    if getattr(tool, "_zentinelle_governed", False):
        return tool

    original_forward = tool.forward

    def forward(*args, **kwargs):
        name = getattr(tool, "name", "unknown")
        try:
            result = client.can_call_tool(name, user_id)
        except Exception as exc:  # noqa: BLE001
            if fail_open:
                logger.warning("Tool check failed, allowing %s: %s", name, exc)
                return original_forward(*args, **kwargs)
            raise PolicyViolationError(
                f"Policy check for tool '{name}' failed and fail_open is off: {exc}"
            ) from exc

        if not result.allowed:
            raise PolicyViolationError(
                f"Tool '{name}' was refused by policy: "
                f"{result.reason or 'no reason given'}",
                result,
            )

        output = original_forward(*args, **kwargs)
        try:
            client.emit_tool_call(tool_name=name, user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record tool call: %s", exc)
        return output

    tool.forward = forward
    tool._zentinelle_governed = True
    return tool


def govern_tools(tools, client: Any, user_id: Optional[str] = None,
                 fail_open: bool = False):
    """`governed_tool` over a list, for passing straight to an agent."""
    return [governed_tool(t, client, user_id, fail_open) for t in tools]
