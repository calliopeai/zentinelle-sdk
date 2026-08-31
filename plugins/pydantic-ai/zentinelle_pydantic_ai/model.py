"""Point a Pydantic AI model at a Zentinelle gateway.

Pydantic AI keeps the endpoint on the provider rather than the model, so the
base URL goes on ``OpenAIProvider`` and the model is handed the provider.
"""
from __future__ import annotations

from typing import Any, Optional

from zentinelle.gateway import (
    DEFAULT_PROVIDER,
    gateway_base_url,
    resolve_gateway_key,
    resolve_gateway_url,
)


def gateway_provider(
    gateway_url: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    **provider_kwargs: Any,
):
    """An ``OpenAIProvider`` pointed at the gateway."""
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIProvider(
        base_url=gateway_base_url(resolve_gateway_url(gateway_url), provider),
        api_key=resolve_gateway_key(api_key),
        **provider_kwargs,
    )


def gateway_model(
    model_name: str,
    gateway_url: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    **provider_kwargs: Any,
):
    """An ``OpenAIChatModel`` whose requests go through the gateway.

    Chat Completions rather than Responses, which is what `OpenAIChatModel`
    speaks. Both are routed and metered, so this is a naming detail rather
    than a constraint.
    """
    from pydantic_ai.models.openai import OpenAIChatModel

    return OpenAIChatModel(
        model_name,
        provider=gateway_provider(gateway_url, api_key, provider, **provider_kwargs),
    )
