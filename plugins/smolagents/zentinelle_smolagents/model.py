"""Point a smolagents model at a Zentinelle gateway.

smolagents spells the base URL differently per model class: `OpenAIModel` and
`LiteLLMModel` take `api_base`, while `InferenceClientModel` takes `base_url`
and calls the key `token`. This builds the OpenAI-compatible one, which is what
a gateway speaks.
"""
from __future__ import annotations

from typing import Any, Optional

from zentinelle.gateway import (
    DEFAULT_PROVIDER,
    gateway_base_url,
    resolve_gateway_key,
    resolve_gateway_url,
)


def gateway_model(
    model_id: str,
    gateway_url: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    **model_kwargs: Any,
):
    """An ``OpenAIModel`` whose requests go through the gateway.

    Routing alone is not governance: wrap the result in `ZentinelleModel` to
    have policy evaluated, and the tools in `govern_tools`.
    """
    from smolagents.models import OpenAIModel

    return OpenAIModel(
        model_id=model_id,
        api_base=gateway_base_url(resolve_gateway_url(gateway_url), provider),
        api_key=resolve_gateway_key(api_key),
        **model_kwargs,
    )
