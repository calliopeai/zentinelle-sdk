"""Point the OpenAI Agents SDK at a Zentinelle gateway.

The Agents SDK has no interception point for the LLM call itself: it builds an
``AsyncOpenAI`` client and talks to it directly. The integration path is
therefore the base URL. Every model call the SDK makes goes to the gateway,
which evaluates policy before forwarding and records tokens on the way back, so
enforcement holds for calls the SDK makes on its own account (summarisation,
handoff decisions, structured-output retries) and not only for the ones the
application makes deliberately.
"""
from __future__ import annotations

import os
from typing import Any, Optional

DEFAULT_PROVIDER = "openai"


def gateway_base_url(gateway_url: str, provider: str = DEFAULT_PROVIDER) -> str:
    """The base URL an OpenAI client should use to reach ``provider``.

    The gateway routes on path: ``/proxy/{provider}/...`` is explicit, and it
    supplies the ``/v1`` the OpenAI client omits from a base URL it will append
    to. ``/v1`` alone would also be routed, by auto-detection, but naming the
    provider means a deployment that fronts several providers keeps working
    when the auto-detection rules change.
    """
    base = gateway_url.rstrip("/")
    return f"{base}/proxy/{provider}/v1"


def gateway_client(
    gateway_url: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    **client_kwargs: Any,
):
    """An ``AsyncOpenAI`` client that talks to the gateway instead of OpenAI.

    ``api_key`` is what the gateway authenticates the *agent* with, not the
    provider credential. A deployment that holds provider keys at the gateway
    never gives them to the agent process at all, which is most of the point:
    the key cannot leak from a place it was never present. When the gateway is
    not holding the key it forwards the one it is given, so passing a real
    ``sk-`` key here also works.
    """
    from openai import AsyncOpenAI  # imported late: only needed when configuring

    gateway_url = gateway_url or os.environ.get("ZENTINELLE_GATEWAY_URL")
    if not gateway_url:
        raise ValueError(
            "No gateway URL. Pass gateway_url= or set ZENTINELLE_GATEWAY_URL."
        )

    api_key = (
        api_key
        or os.environ.get("ZENTINELLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        # The OpenAI client refuses to construct without one. The gateway is
        # what decides whether this request is allowed, so a placeholder here
        # is a rejected request rather than an unauthenticated call to OpenAI.
        or "zentinelle-gateway"
    )

    return AsyncOpenAI(
        base_url=gateway_base_url(gateway_url, provider),
        api_key=api_key,
        **client_kwargs,
    )


def configure(
    gateway_url: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    zentinelle_client: Any = None,
    send_traces_to_openai: bool = False,
    **client_kwargs: Any,
):
    """Install the gateway client as the SDK's default, process-wide.

    ``send_traces_to_openai`` defaults to False, and that default is the
    governed one. The SDK's stock tracing exporter uploads prompts, tool
    arguments and outputs to OpenAI's trace store; on a product whose job is to
    keep a customer's agent traffic inside a boundary they control, exporting
    the same content to a third party by default would undo the deployment. Set
    it True to opt back in.

    Passing ``zentinelle_client`` also replaces the trace processors with one
    that records spans as Zentinelle audit events, so the run is still
    observable, just in the customer's own system.
    """
    import agents

    client = gateway_client(gateway_url, api_key, provider, **client_kwargs)

    # use_for_tracing decides whether this client's key is used to upload
    # traces to OpenAI. It is the agent's gateway key, not an OpenAI key, so
    # handing it to the trace exporter would authenticate nothing and send the
    # payload anyway.
    agents.set_default_openai_client(client, use_for_tracing=send_traces_to_openai)

    if zentinelle_client is not None:
        from .tracing import ZentinelleTracingProcessor

        processor = ZentinelleTracingProcessor(zentinelle_client)
        if send_traces_to_openai:
            agents.add_trace_processor(processor)
        else:
            # Replaces the OpenAI exporter rather than adding to it.
            agents.set_trace_processors([processor])
    elif not send_traces_to_openai:
        # Nowhere to send spans and no permission to send them upstream, so
        # stop the exporter rather than let it retry against an endpoint the
        # gateway key cannot authenticate to.
        agents.set_tracing_disabled(True)

    return client
