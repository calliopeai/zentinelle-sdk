"""
Zentinelle BeeAI Framework Integration - AI Agent Governance.

agent_type: ``bee_agent``

For IBM's Bee Agent Framework (``beeai-framework``).

Usage:
    from beeai_framework.agents.tool_calling import ToolCallingAgent
    from zentinelle import ZentinelleClient
    from zentinelle_bee_agent import ZentinelleGuard, gateway_model

    client = ZentinelleClient(api_key="sk_agent_...", agent_type="bee_agent")
    guard = ZentinelleGuard(client)

    llm = gateway_model("gpt-5", gateway_url="https://gateway.internal")
    guard.attach_model(llm)

    agent = ToolCallingAgent(llm=llm, tools=tools, memory=memory)
    for tool in tools:
        guard.attach_tool(tool)

    # or, covering the whole run in one subscription:
    guard.attach_agent(agent)

BeeAI's emitter is one of the few event systems that can genuinely refuse a
call. A listener's exception is wrapped as an `EmitterError` and re-raised
rather than logged and dropped, and the `"start"` event fires before the work
happens: ahead of `Tool._run` for a tool, and ahead of the provider call for a
chat model. So raising from a `"start"` listener stops it.

`attach_agent` matters for `ReActAgent` and `ToolCallingAgent`, which take no
middleware argument at all; subscribing on the agent's own emitter still sees
the model and tool events, because child emitters pipe into it.
"""

from .governed import AGENT_TYPE, PolicyViolationError, ZentinelleGuard
from .model import gateway_model

__version__ = "0.1.0"

__all__ = [
    "AGENT_TYPE",
    "PolicyViolationError",
    "ZentinelleGuard",
    "gateway_model",
]
