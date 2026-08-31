"""A governed chat generator for Haystack pipelines.

Haystack has no pipeline-level hook: a `Pipeline` runs components, and a
component's `run` is called directly. So the interception point is a component
of our own that wraps the real generator, checks policy, calls it, and records
what came back. Put it where the generator went and the connections are
unchanged.

`haystack.components.agents.Agent` does have hooks, and `ZentinelleToolHook`
covers those. This component is what governs the other case, which is most of
Haystack: a plain pipeline with a generator in it.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from haystack import component
from haystack.dataclasses import ChatMessage

from .errors import PolicyViolationError

logger = logging.getLogger(__name__)

AGENT_TYPE = "haystack"

_CONTENT_LIMIT = 4000


def _summarise(messages, limit: int = _CONTENT_LIMIT) -> str:
    if isinstance(messages, str):
        return messages[:limit]
    parts = []
    for message in list(messages or [])[-4:]:
        text = getattr(message, "text", None)
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)[:limit]


@component
class ZentinelleChatGenerator:
    """Wraps a chat generator with policy checks and usage accounting.

    The wrapped generator is constructed by the caller, so any generator with a
    compatible `run` works, not only OpenAI's; use `gateway_generator()` to
    build one already pointed at a Zentinelle gateway.
    """

    def __init__(
        self,
        generator: Any,
        client: Any,
        user_id: Optional[str] = None,
        evaluate_input: bool = True,
        evaluate_output: bool = True,
        track_token_usage: bool = True,
        fail_open: bool = False,
    ):
        self.generator = generator
        self.client = client
        self.user_id = user_id
        self.evaluate_input = evaluate_input
        self.evaluate_output = evaluate_output
        self.track_token_usage = track_token_usage
        self.fail_open = fail_open

    def warm_up(self) -> None:
        warm_up = getattr(self.generator, "warm_up", None)
        if callable(warm_up):
            warm_up()

    @component.output_types(replies=list[ChatMessage])
    def run(self, messages, **kwargs):
        if self.evaluate_input:
            self._check(
                "model_request",
                {"direction": "input", "harness": AGENT_TYPE,
                 "content": _summarise(messages)},
            )

        output = self.generator.run(messages, **kwargs)
        replies = output.get("replies", []) if isinstance(output, dict) else []

        if self.track_token_usage:
            for reply in replies:
                self._track(reply)

        if self.evaluate_output:
            self._check(
                "model_response",
                {"direction": "output", "harness": AGENT_TYPE,
                 "content": _summarise(replies)},
            )

        return {"replies": replies}

    # -- internals --------------------------------------------------------

    def _check(self, action: str, context: dict) -> None:
        try:
            result = self.client.evaluate(action, self.user_id, context)
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Zentinelle check failed, allowing: %s", exc)
                return
            raise PolicyViolationError(
                f"Zentinelle policy check failed and fail_open is off: {exc}"
            ) from exc

        if not result.allowed:
            raise PolicyViolationError(
                f"Refused by policy: {result.reason or 'no reason given'}", result
            )

    def _track(self, reply) -> None:
        meta = getattr(reply, "meta", None) or {}
        usage = meta.get("usage") or {}
        if not usage:
            return
        try:
            from zentinelle import ModelUsage

            self.client.track_usage(
                ModelUsage(
                    provider="openai",
                    model=meta.get("model") or "unknown",
                    # Haystack passes the provider's usage object through
                    # unchanged, so these are the provider's names.
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


def gateway_generator(
    model: str = "gpt-5-mini",
    gateway_url: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = "openai",
    **generator_kwargs: Any,
):
    """An ``OpenAIChatGenerator`` pointed at the gateway."""
    from haystack.components.generators.chat import OpenAIChatGenerator
    from haystack.utils import Secret
    from zentinelle.gateway import (
        gateway_base_url,
        resolve_gateway_key,
        resolve_gateway_url,
    )

    return OpenAIChatGenerator(
        model=model,
        api_base_url=gateway_base_url(resolve_gateway_url(gateway_url), provider),
        api_key=Secret.from_token(resolve_gateway_key(api_key)),
        **generator_kwargs,
    )
