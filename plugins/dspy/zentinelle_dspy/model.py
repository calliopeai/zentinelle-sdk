"""Point a DSPy LM at a Zentinelle gateway.

DSPy has no `api_base` parameter of its own: `LM` forwards unrecognised keyword
arguments to litellm, and `api_base` / `api_key` are litellm's names. So they
are passed through rather than named in DSPy's signature.
"""
from __future__ import annotations

from typing import Any, Optional

from zentinelle.gateway import (
    DEFAULT_PROVIDER,
    gateway_base_url,
    resolve_gateway_key,
    resolve_gateway_url,
)


def gateway_lm_kwargs(
    gateway_url: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """The litellm kwargs that point an LM at the gateway."""
    return {
        "api_base": gateway_base_url(resolve_gateway_url(gateway_url), provider),
        "api_key": resolve_gateway_key(api_key),
    }


def gateway_lm(
    model: str,
    gateway_url: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    **lm_kwargs: Any,
):
    """A plain `dspy.LM` routed through the gateway.

    Routing is not governance: this LM's calls are proxied and metered, but no
    policy is evaluated in-process. Use `ZentinelleLM` for that, which takes
    the same kwargs.
    """
    from dspy.clients.lm import LM

    return LM(model, **gateway_lm_kwargs(gateway_url, api_key, provider), **lm_kwargs)
