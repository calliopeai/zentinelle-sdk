"""Tests for the Zentinelle Haystack plugin.

Haystack is not installed. The `@component` decorator is stubbed as a no-op
that also carries `output_types`, which is all the plugin's module needs at
import time.
"""

import sys
import types
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest


def _install_haystack_stubs():
    root = types.ModuleType("haystack")
    dataclasses_mod = types.ModuleType("haystack.dataclasses")

    def component(cls):
        return cls

    def output_types(**kwargs):
        def decorator(func):
            return func

        return decorator

    component.output_types = output_types

    @dataclass
    class ChatMessage:
        _text: Optional[str] = None
        _meta: dict = field(default_factory=dict)

        @property
        def text(self):
            return self._text

        @property
        def meta(self):
            return self._meta

    root.component = component
    root.dataclasses = dataclasses_mod
    dataclasses_mod.ChatMessage = ChatMessage

    sys.modules["haystack"] = root
    sys.modules["haystack.dataclasses"] = dataclasses_mod
    return ChatMessage


ChatMessage = _install_haystack_stubs()

from zentinelle_haystack import (  # noqa: E402
    PolicyViolationError,
    ZentinelleChatGenerator,
    ZentinelleToolHook,
)


@dataclass
class FakeResult:
    allowed: bool
    reason: Optional[str] = None


class FakeClient:
    def __init__(self, allowed=True, reason=None, raises=None):
        self.allowed = allowed
        self.reason = reason
        self.raises = raises
        self.evaluated = []
        self.tool_checks = []
        self.usage = []
        self.events = []

    def evaluate(self, action, user_id=None, context=None):
        if self.raises:
            raise self.raises
        self.evaluated.append((action, context))
        return FakeResult(self.allowed, self.reason)

    def can_call_tool(self, tool_name, user_id=None):
        if self.raises:
            raise self.raises
        self.tool_checks.append(tool_name)
        return FakeResult(self.allowed, self.reason)

    def track_usage(self, usage):
        self.usage.append(usage)

    def emit_tool_call(self, tool_name, user_id=None, **kwargs):
        self.events.append(tool_name)


class FakeGenerator:
    def __init__(self, replies=None):
        self.replies = replies or [
            ChatMessage(
                "the answer",
                {"model": "gpt-5-mini",
                 "usage": {"prompt_tokens": 15, "completion_tokens": 36}},
            )
        ]
        self.calls = 0

    def run(self, messages, **kwargs):
        self.calls += 1
        return {"replies": self.replies}


class FakeState:
    def __init__(self, data):
        self.data = data


# ---- the generator component -------------------------------------------


def test_a_denied_request_never_reaches_the_generator():
    zen = FakeClient(allowed=False, reason="contains a credential")
    generator = FakeGenerator()
    governed = ZentinelleChatGenerator(generator, zen)

    with pytest.raises(PolicyViolationError):
        governed.run([ChatMessage("here is my key")])

    assert generator.calls == 0, "the generator ran despite the request being refused"


def test_an_allowed_request_returns_the_replies():
    zen = FakeClient(allowed=True)
    governed = ZentinelleChatGenerator(FakeGenerator(), zen)

    out = governed.run([ChatMessage("hello")])

    assert [r.text for r in out["replies"]] == ["the answer"]


def test_token_usage_is_read_from_reply_meta():
    zen = FakeClient()
    governed = ZentinelleChatGenerator(FakeGenerator(), zen)

    governed.run([ChatMessage("hello")])

    assert zen.usage[0].input_tokens == 15
    assert zen.usage[0].output_tokens == 36
    assert zen.usage[0].model == "gpt-5-mini"


def test_a_denied_reply_is_refused_after_generation():
    """Output checking catches what input checking cannot."""
    zen = FakeClient(allowed=True)
    governed = ZentinelleChatGenerator(FakeGenerator(), zen, evaluate_input=False)
    zen.allowed = False
    zen.reason = "leaks an internal hostname"

    with pytest.raises(PolicyViolationError):
        governed.run([ChatMessage("hello")])

    assert zen.evaluated[0][0] == "model_response"


def test_an_unreachable_control_plane_refuses_by_default():
    zen = FakeClient(raises=RuntimeError("down"))
    generator = FakeGenerator()

    with pytest.raises(PolicyViolationError):
        ZentinelleChatGenerator(generator, zen).run([ChatMessage("hello")])

    assert generator.calls == 0


def test_fail_open_allows_when_the_check_fails():
    zen = FakeClient(raises=RuntimeError("down"))
    generator = FakeGenerator()

    out = ZentinelleChatGenerator(generator, zen, fail_open=True).run(
        [ChatMessage("hello")]
    )

    assert generator.calls == 1
    assert out["replies"]


def test_warm_up_reaches_the_wrapped_generator():
    generator = FakeGenerator()
    generator.warmed = False

    def warm_up():
        generator.warmed = True

    generator.warm_up = warm_up
    ZentinelleChatGenerator(generator, FakeClient()).warm_up()

    assert generator.warmed is True


# ---- the agent tool hook -----------------------------------------------


def test_the_hook_is_restricted_to_before_tool():
    assert ZentinelleToolHook(FakeClient()).allowed_hook_points == ("before_tool",)


def test_a_denied_tool_call_stops_the_run():
    zen = FakeClient(allowed=False, reason="not on the allowlist")
    hook = ZentinelleToolHook(zen)
    state = FakeState(
        {"messages": [types.SimpleNamespace(
            tool_calls=[types.SimpleNamespace(tool_name="delete_records")])]}
    )

    with pytest.raises(PolicyViolationError) as excinfo:
        hook.run(state)

    assert "delete_records" in str(excinfo.value)


def test_every_pending_tool_call_is_checked():
    zen = FakeClient(allowed=True)
    hook = ZentinelleToolHook(zen)
    state = FakeState(
        {"messages": [types.SimpleNamespace(tool_calls=[
            types.SimpleNamespace(tool_name="a"),
            types.SimpleNamespace(tool_name="b"),
        ])]}
    )

    hook.run(state)

    assert zen.tool_checks == ["a", "b"]


def test_a_message_with_no_tool_calls_is_a_no_op():
    zen = FakeClient()
    hook = ZentinelleToolHook(zen)

    hook.run(FakeState({"messages": [types.SimpleNamespace(tool_calls=[])]}))
    hook.run(FakeState({}))

    assert zen.tool_checks == []
