"""The gateway routing rule, which every framework plugin depends on.

This used to live in each plugin. It is here now because seven copies of a
routing rule is seven places to fix when the gateway's paths change, and
because the two failure modes below are silent: a doubled slash produces a
request the gateway does not recognise, and a missing gateway URL would
otherwise let an agent talk straight to the provider while looking configured.
"""

import os

import pytest

from zentinelle.gateway import (
    gateway_base_url,
    resolve_gateway_key,
    resolve_gateway_url,
)


def test_the_provider_is_named_in_the_path():
    assert gateway_base_url("https://gw.internal") == "https://gw.internal/proxy/openai/v1"


def test_another_provider():
    assert (
        gateway_base_url("https://gw.internal", "anthropic")
        == "https://gw.internal/proxy/anthropic/v1"
    )


def test_a_trailing_slash_does_not_become_a_double_slash():
    """`//proxy` does not match the gateway's prefix check.

    The request is then forwarded nowhere, and nothing about the configuration
    looks wrong, which is why this is worth a test rather than a comment.
    """
    assert (
        gateway_base_url("https://gw.internal/") == "https://gw.internal/proxy/openai/v1"
    )
    assert "//proxy" not in gateway_base_url("https://gw.internal/")


def test_a_path_prefix_is_preserved():
    """A gateway behind a path-routing ingress is still reachable."""
    assert (
        gateway_base_url("https://internal/zentinelle")
        == "https://internal/zentinelle/proxy/openai/v1"
    )


def test_a_missing_gateway_url_is_refused_not_defaulted(monkeypatch):
    """Defaulting to the provider would leave the agent ungoverned.

    An agent that silently talked straight to OpenAI because a variable was
    unset is the failure this refusal exists to prevent.
    """
    monkeypatch.delenv("ZENTINELLE_GATEWAY_URL", raising=False)

    with pytest.raises(ValueError):
        resolve_gateway_url()


def test_the_environment_supplies_the_gateway_url(monkeypatch):
    monkeypatch.setenv("ZENTINELLE_GATEWAY_URL", "https://from-env")

    assert resolve_gateway_url() == "https://from-env"


def test_an_explicit_url_beats_the_environment(monkeypatch):
    monkeypatch.setenv("ZENTINELLE_GATEWAY_URL", "https://from-env")

    assert resolve_gateway_url("https://explicit") == "https://explicit"


def test_the_key_falls_back_to_a_placeholder(monkeypatch):
    """Most provider clients refuse to construct without a key.

    With the placeholder, a misconfigured agent gets a refusal from the gateway
    rather than an unauthenticated call to the provider.
    """
    monkeypatch.delenv("ZENTINELLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert resolve_gateway_key() == "zentinelle-gateway"


def test_an_explicit_key_wins(monkeypatch):
    monkeypatch.setenv("ZENTINELLE_API_KEY", "from-env")

    assert resolve_gateway_key("sk_agent_explicit") == "sk_agent_explicit"


def test_the_zentinelle_key_is_preferred_over_the_provider_key(monkeypatch):
    """The gateway authenticates the agent, so its own key comes first."""
    monkeypatch.setenv("ZENTINELLE_API_KEY", "sk_agent_x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-provider")

    assert resolve_gateway_key() == "sk_agent_x"
