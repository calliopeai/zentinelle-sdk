"""
Zentinelle Letta (MemGPT) Integration - AI Agent Governance.

agent_type: ``letta``

Usage:
    from letta_client import Letta
    from zentinelle import ZentinelleClient
    from zentinelle_letta import GovernedLetta

    client = ZentinelleClient(api_key="sk_agent_...", agent_type="letta")
    letta = GovernedLetta(Letta(api_key="..."), client, audit_memory=True)

    response = letta.send_message(agent_id="agent-1", messages=[...])

**What this can and cannot do.** Letta runs the agent loop on a server. The
Python package is a generated REST client with no hook, middleware or
interceptor, so the only place a client-side integration can stand is the call
site.

Enforced: whether a message may be sent. Recorded: token usage, and memory
block changes by diffing around the call. Not possible from here: blocking an
individual tool call, or reacting to a memory edit as it happens, because both
occur server-side after the request was allowed.

`require_tool_approval()` sets Letta's own server-side approval flag on named
tools. That is Letta gating the tool, not Zentinelle; it is exposed because it
is the only thing that stops a Letta tool call.
"""

from .governed import (
    AGENT_TYPE,
    GovernedLetta,
    PolicyViolationError,
    require_tool_approval,
)

__version__ = "0.1.0"

__all__ = [
    "AGENT_TYPE",
    "GovernedLetta",
    "PolicyViolationError",
    "require_tool_approval",
]
