"""Point a Mistral client at a Zentinelle gateway.

Mistral's SDK takes a whole `server_url` rather than an OpenAI-style base URL,
and its paths already start with `/v1`, so the gateway route must not supply a
second one.
"""
from __future__ import annotations

from typing import Optional

from zentinelle.gateway import resolve_gateway_url


def gateway_server_url(
    gateway_url: Optional[str] = None,
    provider: str = "mistral",
) -> str:
    """The ``server_url`` a Mistral client should use.

    Deliberately not `zentinelle.gateway.gateway_base_url`: that appends
    ``/v1`` for OpenAI-compatible clients, and the Mistral SDK adds its own
    ``/v1`` to every path. Using it here would produce ``/v1/v1/...``.
    """
    return f"{resolve_gateway_url(gateway_url).rstrip('/')}/proxy/{provider}"
