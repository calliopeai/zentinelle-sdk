"""Where a Zentinelle gateway lives, and how a provider SDK reaches it.

Every framework plugin needs the same two lines: turn a gateway URL into the
base URL an OpenAI-compatible client should use, and work out which key to
present. They lived in the plugins, which meant one copy per framework and
seven places to fix a routing change. One copy here instead.
"""
from __future__ import annotations

import os
from typing import Optional

DEFAULT_PROVIDER = "openai"


def gateway_base_url(gateway_url: str, provider: str = DEFAULT_PROVIDER) -> str:
    """The base URL a provider client should use to reach ``provider``.

    The gateway routes on path. ``/proxy/{provider}/...`` names the provider
    explicitly, and the trailing ``/v1`` is the part an OpenAI-compatible
    client appends its own paths to. ``/v1`` alone is also routed, by
    auto-detection, but naming the provider keeps a deployment fronting
    several providers working if those auto-detection rules change.

    The trailing slash is stripped because a doubled one (``//proxy``) does not
    match the gateway's prefix check, and the resulting request is forwarded
    nowhere.
    """
    base = gateway_url.rstrip("/")
    return f"{base}/proxy/{provider}/v1"


def resolve_gateway_url(gateway_url: Optional[str] = None) -> str:
    """The configured gateway, or a refusal.

    Refusing beats defaulting to the provider's own endpoint: an agent that
    silently talked straight to OpenAI because a variable was unset would be
    ungoverned while looking configured.
    """
    gateway_url = gateway_url or os.environ.get("ZENTINELLE_GATEWAY_URL")
    if not gateway_url:
        raise ValueError(
            "No gateway URL. Pass gateway_url= or set ZENTINELLE_GATEWAY_URL."
        )
    return gateway_url


def resolve_gateway_key(api_key: Optional[str] = None) -> str:
    """The key to present to the gateway.

    This authenticates the *agent*, not the provider. A deployment holding
    provider credentials at the gateway never puts them in the agent process,
    which is the point: a key that was never there cannot leak from there.
    When the gateway is not holding one, it forwards whatever it is given, so
    a real provider key also works.

    The placeholder exists because most provider clients refuse to construct
    without some key. With it, a misconfigured agent gets a refusal from the
    gateway rather than an unauthenticated call to the provider.
    """
    return (
        api_key
        or os.environ.get("ZENTINELLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or "zentinelle-gateway"
    )
