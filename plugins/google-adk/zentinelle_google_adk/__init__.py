"""
Zentinelle Google ADK Integration - AI Agent Governance.

agent_type: ``google_adk``

Usage:
    from google.adk.agents import LlmAgent
    from google.adk.runners import Runner
    from zentinelle import ZentinelleClient
    from zentinelle_google_adk import ZentinellePlugin

    client = ZentinelleClient(api_key="sk_agent_...", agent_type="google_adk")

    runner = Runner(
        agent=LlmAgent(name="assistant", model="gemini-2.0-flash"),
        plugins=[ZentinellePlugin(client)],
        app_name="my-app",
        session_service=...,
    )

Registered as an ADK *plugin* rather than as per-agent callbacks. A plugin
covers every agent the runner drives, including sub-agents created at runtime,
so governance cannot be sidestepped by adding an agent; and ADK gives plugin
callbacks precedence over an agent's own, so an agent cannot pre-empt it.

Denials are returned, not raised: ADK's contract is that a `before_*` callback
returning non-None short-circuits what follows and its value becomes the
result. The refusal therefore arrives as a model response or a tool error dict.

To route calls through a Zentinelle gateway as well, use `gateway_model()`,
which builds a `LiteLlm` model pointed at it.
"""

from .model import gateway_model
from .plugin import AGENT_TYPE, ZentinellePlugin

__version__ = "0.1.0"

__all__ = [
    "AGENT_TYPE",
    "ZentinellePlugin",
    "gateway_model",
]
