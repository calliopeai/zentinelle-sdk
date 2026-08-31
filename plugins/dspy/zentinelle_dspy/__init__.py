"""
Zentinelle DSPy Integration - AI Agent Governance.

agent_type: ``dspy``

Usage:
    import dspy
    from zentinelle import ZentinelleClient
    from zentinelle_dspy import ZentinelleLM, govern_tools, gateway_lm_kwargs

    client = ZentinelleClient(api_key="sk_agent_...", agent_type="dspy")

    dspy.configure(lm=ZentinelleLM(
        client,
        "openai/gpt-5",
        **gateway_lm_kwargs(gateway_url="https://gateway.internal"),
    ))

DSPy's `BaseCallback` looks like the integration point and is not one. Its
dispatcher catches every exception a callback raises, logs it, and proceeds to
call the wrapped function, so `on_lm_start` cannot refuse a request. That is
why enforcement is `ZentinelleLM` and `govern_tools` rather than a callback.

`ZentinelleCallback` is available for audit and is audit only.
"""

from .callbacks import ZentinelleCallback
from .governed import (
    AGENT_TYPE,
    PolicyViolationError,
    ZentinelleLM,
    govern_tools,
    governed_tool,
)
from .model import gateway_lm, gateway_lm_kwargs

__version__ = "0.1.0"

__all__ = [
    "AGENT_TYPE",
    "PolicyViolationError",
    "ZentinelleCallback",
    "ZentinelleLM",
    "gateway_lm",
    "gateway_lm_kwargs",
    "govern_tools",
    "governed_tool",
]
