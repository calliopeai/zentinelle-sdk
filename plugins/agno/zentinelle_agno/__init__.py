"""
Zentinelle Agno Integration - AI Agent Governance.

agent_type: ``agno``

Usage:
    from agno.agent import Agent
    from zentinelle import ZentinelleClient
    from zentinelle_agno import ZentinelleGuard, gateway_model

    client = ZentinelleClient(api_key="sk_agent_...", agent_type="agno")
    guard = ZentinelleGuard(client)

    agent = Agent(
        model=gateway_model("gpt-5", gateway_url="https://gateway.internal"),
        pre_hooks=[guard.pre_hook],
        post_hooks=[guard.post_hook],
        tool_hooks=[guard.tool_hook],
    )

All three hooks refuse rather than warn. Agno swallows and logs any exception a
hook raises except `InputCheckError` / `OutputCheckError`, so the plugin raises
those specifically; a plugin that raised anything else would look like it was
enforcing while the run continued.
"""

from .hooks import AGENT_TYPE, PolicyViolationError, ZentinelleGuard
from .model import gateway_model

__version__ = "0.1.0"

__all__ = [
    "AGENT_TYPE",
    "PolicyViolationError",
    "ZentinelleGuard",
    "gateway_model",
]
