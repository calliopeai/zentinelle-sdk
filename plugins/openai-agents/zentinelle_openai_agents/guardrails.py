"""Policy enforcement at the SDK's own stopping points.

Guardrails are the one place the Agents SDK will halt a run on the library's
say-so: a tripped tripwire raises before the agent's output reaches the caller.
Everything else in the SDK is advisory. A governance product that only observes
is a log, so this is where the enforcement lives.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ZentinelleGuardrailError(Exception):
    """A policy check could not be completed and fail_open was off."""


def _summarise(value: Any, limit: int = 4000) -> str:
    """A string for the policy engine, bounded.

    Agent input is a string on the first turn and a list of items after that.
    The whole conversation is not sent: a run that has been going for a while
    would post its entire history on every check, and the policies that read
    content are matching against the current turn.
    """
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, list):
        parts = []
        for item in value[-4:]:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                content = item.get("content")
                parts.append(content if isinstance(content, str) else str(content))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)[:limit]
    return str(value)[:limit]


async def _evaluate(client: Any, action: str, context: dict, fail_open: bool):
    """Run the sync SDK client off the event loop.

    ``ZentinelleClient`` is built on ``requests``, so calling it directly from
    a guardrail would block the loop the agent is running on, and with it every
    other concurrent request in the process.
    """
    try:
        return await asyncio.to_thread(client.evaluate, action, None, context)
    except Exception as exc:  # noqa: BLE001 - the decision is what to do next
        if fail_open:
            logger.warning("Zentinelle policy check failed, allowing: %s", exc)
            return None
        raise ZentinelleGuardrailError(
            f"Zentinelle policy check failed and fail_open is off: {exc}"
        ) from exc


def zentinelle_input_guardrail(
    client: Any,
    fail_open: bool = False,
    name: str = "zentinelle_input",
    agent_name: Optional[str] = None,
):
    """A guardrail that asks Zentinelle whether this input may be processed.

    ``run_in_parallel`` is False. The SDK's default runs a guardrail alongside
    the agent, which is fine for a scoring check but wrong for enforcement: the
    model call, and any tool it triggers, would already be under way by the time
    the denial arrives. A blocked request should not reach the provider at all.
    """
    from agents import GuardrailFunctionOutput, InputGuardrail

    async def check(context, agent, agent_input) -> "GuardrailFunctionOutput":
        result = await _evaluate(
            client,
            "model_request",
            {
                "direction": "input",
                "agent": agent_name or getattr(agent, "name", "unknown"),
                "harness": "openai_agents",
                "content": _summarise(agent_input),
            },
            fail_open,
        )
        if result is None:
            return GuardrailFunctionOutput(output_info=None, tripwire_triggered=False)

        return GuardrailFunctionOutput(
            output_info={
                "allowed": result.allowed,
                "reason": result.reason,
                "blocked_policies": result.blocked_policies,
                "fail_open": result.is_fail_open(),
            },
            tripwire_triggered=not result.allowed,
        )

    return InputGuardrail(guardrail_function=check, name=name, run_in_parallel=False)


def zentinelle_output_guardrail(
    client: Any,
    fail_open: bool = False,
    name: str = "zentinelle_output",
    agent_name: Optional[str] = None,
):
    """A guardrail that checks the agent's final output before it is returned.

    Output checking is the half of content policy that input checking cannot
    do: a prompt that looks harmless can still produce a response that leaks a
    secret or breaches a content rule.
    """
    from agents import GuardrailFunctionOutput, OutputGuardrail

    async def check(context, agent, agent_output) -> "GuardrailFunctionOutput":
        result = await _evaluate(
            client,
            "model_response",
            {
                "direction": "output",
                "agent": agent_name or getattr(agent, "name", "unknown"),
                "harness": "openai_agents",
                "content": _summarise(agent_output),
            },
            fail_open,
        )
        if result is None:
            return GuardrailFunctionOutput(output_info=None, tripwire_triggered=False)

        return GuardrailFunctionOutput(
            output_info={
                "allowed": result.allowed,
                "reason": result.reason,
                "blocked_policies": result.blocked_policies,
                "fail_open": result.is_fail_open(),
            },
            tripwire_triggered=not result.allowed,
        )

    return OutputGuardrail(guardrail_function=check, name=name)
