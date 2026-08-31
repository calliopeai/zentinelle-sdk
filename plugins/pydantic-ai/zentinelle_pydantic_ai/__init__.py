"""
Zentinelle Pydantic AI Integration - AI Agent Governance.

agent_type: ``pydantic_ai``

Two parts:

- ``ZentinelleCapability``: policy enforcement, token accounting and audit,
  registered as a Pydantic AI capability
- ``gateway_model``: an OpenAI model whose calls go through a Zentinelle
  gateway

Usage:
    from pydantic_ai import Agent
    from zentinelle import ZentinelleClient
    from zentinelle_pydantic_ai import ZentinelleCapability, gateway_model

    client = ZentinelleClient(api_key="sk_agent_...", agent_type="pydantic_ai")

    agent = Agent(
        gateway_model("gpt-5", gateway_url="https://gateway.internal"),
        capabilities=[ZentinelleCapability(client)],
    )

    result = await agent.run("...")

The capability enforces; the gateway model routes. They are independent, and a
governed deployment wants both: the capability cannot see a call made by some
other client in the same process, and the gateway cannot refuse a tool call,
because a tool call never reaches it.
"""

from .capability import AGENT_TYPE, PolicyViolationError, ZentinelleCapability
from .model import gateway_model, gateway_provider

__version__ = "0.1.0"

__all__ = [
    "AGENT_TYPE",
    "PolicyViolationError",
    "ZentinelleCapability",
    "gateway_model",
    "gateway_provider",
]
