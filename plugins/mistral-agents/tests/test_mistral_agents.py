"""Tests for the Zentinelle Mistral Agents plugin.

The Mistral SDK is not installed; the plugin wraps whatever client it is given.

Half of these pin the honest boundary rather than behaviour. Mistral runs the
agent loop server-side, so what can be enforced is whether a request is sent,
and the ungoverned fall-through path is documented rather than hidden — which
means it should be tested, so the README and the code cannot drift apart.
"""

import types
from dataclasses import dataclass
from typing import Optional

import pytest

from zentinelle_mistral_agents import (
    GovernedMistral,
    PolicyViolationError,
    gateway_server_url,
    install_request_hook,
)


@dataclass
class FakeResult:
    allowed: bool
    reason: Optional[str] = None


class FakeZentinelle:
    def __init__(self, allowed=True, reason=None, raises=None):
        self.allowed = allowed
        self.reason = reason
        self.raises = raises
        self.evaluated = []
        self.usage = []

    def evaluate(self, action, user_id=None, context=None):
        if self.raises:
            raise self.raises
        self.evaluated.append((action, context))
        return FakeResult(self.allowed, self.reason)

    def track_usage(self, usage):
        self.usage.append(usage)


class FakeMistral:
    """Just enough of mistralai.Mistral's resource tree."""

    def __init__(self):
        self.calls = []
        outer = self
        usage = types.SimpleNamespace(prompt_tokens=25, completion_tokens=6)

        class _Chat:
            def complete(self, **kwargs):
                outer.calls.append(("chat.complete", kwargs))
                return types.SimpleNamespace(usage=usage)

        class _Conversations:
            def start(self, **kwargs):
                outer.calls.append(("conversations.start", kwargs))
                return types.SimpleNamespace(usage=usage)

            def append(self, **kwargs):
                outer.calls.append(("conversations.append", kwargs))
                return types.SimpleNamespace(usage=usage)

        self.chat = _Chat()
        self.beta = types.SimpleNamespace(conversations=_Conversations())
        self.some_other_api = "reachable"


# ---- the one thing it can enforce --------------------------------------


def test_a_denied_request_is_never_sent():
    mistral = FakeMistral()
    zen = FakeZentinelle(allowed=False, reason="contains a credential")

    with pytest.raises(PolicyViolationError) as excinfo:
        GovernedMistral(mistral, zen).chat_complete(
            model="mistral-large-latest", messages=[{"content": "my key"}]
        )

    assert mistral.calls == [], "the request was sent despite being refused"
    assert "contains a credential" in str(excinfo.value)


def test_an_allowed_request_is_sent():
    mistral = FakeMistral()

    GovernedMistral(mistral, FakeZentinelle()).chat_complete(
        model="mistral-large-latest", messages=[{"content": "hello"}]
    )

    assert mistral.calls[0][0] == "chat.complete"


def test_conversations_are_governed_too():
    mistral = FakeMistral()
    zen = FakeZentinelle(allowed=False, reason="no")
    governed = GovernedMistral(mistral, zen)

    with pytest.raises(PolicyViolationError):
        governed.conversation_start(agent_id="a", inputs=[{"content": "x"}])
    with pytest.raises(PolicyViolationError):
        governed.conversation_append(conversation_id="c", inputs=[{"content": "x"}])

    assert mistral.calls == []


def test_an_unreachable_control_plane_refuses_by_default():
    mistral = FakeMistral()
    zen = FakeZentinelle(raises=RuntimeError("down"))

    with pytest.raises(PolicyViolationError):
        GovernedMistral(mistral, zen).chat_complete(model="m", messages=[])

    assert mistral.calls == []


def test_fail_open_sends_when_the_check_fails():
    mistral = FakeMistral()
    zen = FakeZentinelle(raises=RuntimeError("down"))

    GovernedMistral(mistral, zen, fail_open=True).chat_complete(model="m", messages=[])

    assert len(mistral.calls) == 1


def test_token_usage_is_recorded():
    mistral = FakeMistral()
    zen = FakeZentinelle()

    GovernedMistral(mistral, zen).chat_complete(model="mistral-large-latest",
                                                messages=[])

    assert zen.usage[0].input_tokens == 25
    assert zen.usage[0].output_tokens == 6
    assert zen.usage[0].provider == "mistral"


# ---- the boundary -------------------------------------------------------


def test_the_ungoverned_path_is_still_reachable():
    """Attribute access falls through, and the README says so.

    There is no interceptor underneath the wrapper, so reaching past its
    methods bypasses the check. Pinned here so a future change cannot quietly
    make the wrapper look total when it is not.
    """
    mistral = FakeMistral()
    governed = GovernedMistral(mistral, FakeZentinelle(allowed=False, reason="no"))

    governed.chat.complete(model="m", messages=[])

    assert len(mistral.calls) == 1
    assert governed.some_other_api == "reachable"


# ---- the unsupported hook path -----------------------------------------


def test_installing_the_hook_fails_loudly_when_the_internals_moved():
    """Silence here would be the dangerous outcome.

    The registry is a private attribute with no public accessor. If a version
    of the SDK moves it, a deployment that believed it was governed must find
    out at install time rather than never.
    """
    with pytest.raises(RuntimeError) as excinfo:
        install_request_hook(types.SimpleNamespace(), FakeZentinelle())

    assert "GovernedMistral" in str(excinfo.value), (
        "the error should point at the supported alternative"
    )


def test_the_hook_registers_when_the_registry_is_present():
    registered = []
    hooks = types.SimpleNamespace(
        register_before_request_hook=lambda hook: registered.append(hook)
    )
    configuration = types.SimpleNamespace()
    configuration.__dict__["_hooks"] = hooks
    client = types.SimpleNamespace(sdk_configuration=configuration)

    install_request_hook(client, FakeZentinelle())

    assert len(registered) == 1


def test_the_hook_returns_an_exception_rather_than_raising():
    """Mistral's contract: a before_request hook *returns* the exception.

    Raising would escape the SDK's own handling and surface as an unrelated
    error, so the difference is not cosmetic.
    """
    registered = []
    hooks = types.SimpleNamespace(
        register_before_request_hook=lambda hook: registered.append(hook)
    )
    configuration = types.SimpleNamespace()
    configuration.__dict__["_hooks"] = hooks
    client = types.SimpleNamespace(sdk_configuration=configuration)

    install_request_hook(client, FakeZentinelle(allowed=False, reason="no"))
    outcome = registered[0].before_request(
        types.SimpleNamespace(operation_id="chat"), "the-request"
    )

    assert isinstance(outcome, PolicyViolationError)


def test_the_hook_returns_the_request_when_allowed():
    registered = []
    hooks = types.SimpleNamespace(
        register_before_request_hook=lambda hook: registered.append(hook)
    )
    configuration = types.SimpleNamespace()
    configuration.__dict__["_hooks"] = hooks
    client = types.SimpleNamespace(sdk_configuration=configuration)

    install_request_hook(client, FakeZentinelle(allowed=True))
    outcome = registered[0].before_request(
        types.SimpleNamespace(operation_id="chat"), "the-request"
    )

    assert outcome == "the-request"


# ---- gateway routing ----------------------------------------------------


def test_the_gateway_url_does_not_append_a_second_v1():
    """The Mistral SDK adds its own /v1 to every path."""
    url = gateway_server_url("https://gw.internal")

    assert url == "https://gw.internal/proxy/mistral"
    assert "/v1" not in url
