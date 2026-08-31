"""Point a BeeAI chat model at a Zentinelle gateway."""
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
    """An ``OpenAIChatModel`` whose requests go through the gateway."""
    from beeai_framework.adapters.openai import OpenAIChatModel

    return OpenAIChatModel(
        model_id,
        base_url=gateway_base_url(resolve_gateway_url(gateway_url), provider),
        api_key=resolve_gateway_key(api_key),
        **model_kwargs,
    )
