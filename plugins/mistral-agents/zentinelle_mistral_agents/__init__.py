"""
Zentinelle Mistral Agents Integration - AI Agent Governance.

agent_type: ``mistral_agents``

Usage:
    from mistralai.client import Mistral
    from zentinelle import ZentinelleClient
    from zentinelle_mistral_agents import GovernedMistral

    client = ZentinelleClient(api_key="sk_agent_...", agent_type="mistral_agents")
    mistral = GovernedMistral(Mistral(api_key="..."), client)

    response = mistral.chat_complete(model="mistral-large-latest", messages=[...])

**What this can and cannot do.** Mistral's Agents API is a server-side runtime.
The agent loop, and every server-side tool (web search, code interpreter,
connectors, document library), run on Mistral's infrastructure between your
request and your response.

Enforced: whether a request is sent. Recorded: token usage. Not possible:
blocking an individual server-side tool call — the client never sees one, and
there is no hook type for it anywhere in the SDK. For client-side function
tools you already control execution, so no gate is needed; Mistral returns the
tool call and you decide whether to run it.

`install_request_hook()` covers every request through a client, not just the
methods here, but does so through a private SDK attribute and is unsupported.
Read its docstring before using it.

To route through a Zentinelle gateway instead, pass `server_url=` to `Mistral`.
`gateway_server_url()` builds the value.
"""

from .governed import (
    AGENT_TYPE,
    GovernedMistral,
    PolicyViolationError,
    install_request_hook,
)
from .model import gateway_server_url

__version__ = "0.1.0"

__all__ = [
    "AGENT_TYPE",
    "GovernedMistral",
    "PolicyViolationError",
    "gateway_server_url",
    "install_request_hook",
]
