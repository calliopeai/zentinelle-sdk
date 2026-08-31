"""
Zentinelle Haystack Integration - AI Agent Governance.

agent_type: ``haystack``

Two entry points, because Haystack has two shapes:

- ``ZentinelleChatGenerator``: a component that wraps a chat generator. This is
  the one for a plain `Pipeline`, which has no hook points at all.
- ``ZentinelleToolHook``: a `before_tool` hook for
  `haystack.components.agents.Agent`, which does.

Usage:
    from haystack import Pipeline
    from zentinelle import ZentinelleClient
    from zentinelle_haystack import ZentinelleChatGenerator, gateway_generator

    client = ZentinelleClient(api_key="sk_agent_...", agent_type="haystack")

    pipeline = Pipeline()
    pipeline.add_component(
        "llm",
        ZentinelleChatGenerator(
            gateway_generator("gpt-5-mini", gateway_url="https://gateway.internal"),
            client,
        ),
    )

Note for anyone porting an older integration: `ToolInvoker` does not exist in
haystack-ai 3.x. Tools run inside the Agent, which is why tool governance is a
hook rather than a component.
"""

from .errors import PolicyViolationError
from .generator import AGENT_TYPE, ZentinelleChatGenerator, gateway_generator
from .hooks import ZentinelleToolHook

__version__ = "0.1.0"

__all__ = [
    "AGENT_TYPE",
    "PolicyViolationError",
    "ZentinelleChatGenerator",
    "ZentinelleToolHook",
    "gateway_generator",
]
