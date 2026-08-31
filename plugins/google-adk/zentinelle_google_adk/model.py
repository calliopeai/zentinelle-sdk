"""Route an ADK agent's model calls through a Zentinelle gateway.

ADK talks to Gemini natively and to everything else through `LiteLlm`, which
forwards unrecognised keyword arguments straight to litellm's `completion()`.
`api_base` and `api_key` are litellm's names, not ADK's; ADK does not know
about them, which is why they are passed through rather than named in its own
signature.

A native Gemini model has no base-URL override, so a deployment that wants
every call to traverse the gateway runs its models through LiteLlm.
"""
from __future__ import annotations

from typing import Any, Optional

from zentinelle.gateway import (
    gateway_base_url,
    resolve_gateway_key,
    resolve_gateway_url,
)


def gateway_model(
    model: str,
    gateway_url: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = "openai",
    **litellm_kwargs: Any,
):
    """A ``LiteLlm`` model whose requests go through the gateway.

    ``model`` is a litellm model string, such as ``openai/gpt-5``. ``provider``
    selects the gateway's own route and should match it.
    """
    from google.adk.models import LiteLlm

    return LiteLlm(
        model=model,
        api_base=gateway_base_url(resolve_gateway_url(gateway_url), provider),
        api_key=resolve_gateway_key(api_key),
        **litellm_kwargs,
    )
