"""
Zentinelle smolagents Integration - AI Agent Governance.

agent_type: ``smolagents``

Usage:
    from smolagents import CodeAgent
    from zentinelle import ZentinelleClient
    from zentinelle_smolagents import (
        ZentinelleModel, gateway_model, govern_tools,
    )

    client = ZentinelleClient(api_key="sk_agent_...", agent_type="smolagents")

    agent = CodeAgent(
        model=ZentinelleModel(
            gateway_model("gpt-5", gateway_url="https://gateway.internal"),
            client,
        ),
        tools=govern_tools([my_tool], client),
    )

smolagents has no pre-execution hook: `step_callbacks` runs after the model has
answered and the tool has run, and `final_answer_checks` gates only the final
answer. So enforcement is by wrapping, and both wrappers are needed. The model
wrapper governs what reaches the provider; the tool wrappers govern what the
agent does, which for a `CodeAgent` the model reaches by writing Python rather
than by asking the agent, so there is nothing between it and the tool except
the tool itself.

`ZentinelleStepCallback` is available for audit, and is only audit. Anything it
sees has already happened.
"""

from .callbacks import ZentinelleStepCallback
from .governed import (
    AGENT_TYPE,
    PolicyViolationError,
    ZentinelleModel,
    govern_tools,
    governed_tool,
)
from .model import gateway_model

__version__ = "0.1.0"

__all__ = [
    "AGENT_TYPE",
    "PolicyViolationError",
    "ZentinelleModel",
    "ZentinelleStepCallback",
    "gateway_model",
    "govern_tools",
    "governed_tool",
]
