"""
Zentinelle OpenAI Agents SDK Integration - AI Agent Governance.

Governance for agents built on the OpenAI Agents SDK, in four parts:

- ``configure``: routes the SDK's LLM calls through a Zentinelle gateway
- ``zentinelle_input_guardrail`` / ``zentinelle_output_guardrail``: policy
  enforcement at the SDK's own halting points
- ``ZentinelleRunHooks``: tool-call governance and token accounting
- ``ZentinelleTracingProcessor``: run traces recorded as Zentinelle audit
  events rather than exported to OpenAI

agent_type: ``openai_agents``

Usage:
    from agents import Agent, Runner
    from zentinelle import ZentinelleClient
    from zentinelle_openai_agents import (
        ZentinelleRunHooks,
        configure,
        zentinelle_input_guardrail,
        zentinelle_output_guardrail,
    )

    client = ZentinelleClient(api_key="sk_agent_...", agent_type="openai_agents")
    configure(gateway_url="https://gateway.internal", zentinelle_client=client)

    agent = Agent(
        name="assistant",
        instructions="Help the user.",
        input_guardrails=[zentinelle_input_guardrail(client)],
        output_guardrails=[zentinelle_output_guardrail(client)],
    )

    result = await Runner.run(agent, "...", hooks=ZentinelleRunHooks(client))

The gateway covers the LLM calls; the guardrails and hooks cover the decisions
the SDK makes around them. Use both: a gateway alone cannot refuse a tool call,
and hooks alone cannot see a request the SDK issues on its own account.
"""

from .guardrails import (
    ZentinelleGuardrailError,
    zentinelle_input_guardrail,
    zentinelle_output_guardrail,
)
from .hooks import PolicyViolationError, ZentinelleRunHooks
from .proxy import configure, gateway_base_url, gateway_client
from .tracing import ZentinelleTracingProcessor

__version__ = "0.1.0"

AGENT_TYPE = "openai_agents"

__all__ = [
    "AGENT_TYPE",
    "PolicyViolationError",
    "ZentinelleGuardrailError",
    "ZentinelleRunHooks",
    "ZentinelleTracingProcessor",
    "configure",
    "gateway_base_url",
    "gateway_client",
    "zentinelle_input_guardrail",
    "zentinelle_output_guardrail",
]
