"""Tests for the Zentinelle DSPy plugin.

DSPy is not installed; the stubs mirror the 3.3 contract. The one that carries
an argument is `_install_dspy_stubs`'s dispatcher: DSPy's real `with_callbacks`
catches and logs whatever a callback raises and then calls the wrapped function
anyway, which is why enforcement is not a callback here. That behaviour is
reproduced in the stub so the claim can be tested rather than asserted in prose.
"""

import sys
import types
from dataclasses import dataclass
from typing import Optional

import pytest


def _install_dspy_stubs():
    root = types.ModuleType("dspy")
    clients = types.ModuleType("dspy.clients")
    lm_mod = types.ModuleType("dspy.clients.lm")
    utils = types.ModuleType("dspy.utils")
    callback_mod = types.ModuleType("dspy.utils.callback")

    class LM:
        def __init__(self, model, **kwargs):
            self.model = model
            self.kwargs = kwargs
            self.forwarded = 0

        def forward(self, prompt=None, messages=None, **kwargs):
            self.forwarded += 1
            return types.SimpleNamespace(
                usage={"prompt_tokens": 11, "completion_tokens": 4}
            )

    class BaseCallback:
        def on_lm_start(self, call_id, instance, inputs):
            pass

        def on_lm_end(self, call_id, outputs, exception=None):
            pass

        def on_tool_end(self, call_id, outputs, exception=None):
            pass

        def on_module_end(self, call_id, outputs, exception=None):
            pass

    lm_mod.LM = LM
    callback_mod.BaseCallback = BaseCallback
    clients.lm = lm_mod
    utils.callback = callback_mod
    root.clients = clients
    root.utils = utils

    sys.modules["dspy"] = root
    sys.modules["dspy.clients"] = clients
    sys.modules["dspy.clients.lm"] = lm_mod
    sys.modules["dspy.utils"] = utils
    sys.modules["dspy.utils.callback"] = callback_mod


_install_dspy_stubs()

from zentinelle_dspy import (  # noqa: E402
    PolicyViolationError,
    ZentinelleCallback,
    ZentinelleLM,
    gateway_lm_kwargs,
    govern_tools,
    governed_tool,
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
        self.events.append(("tool_call", tool_name))

    def emit(self, event_type, payload=None, category=None, user_id=None):
        self.events.append((event_type, payload or {}))


class FakeTool:
    """Mirrors dspy.Tool: __call__ validates then calls self.func."""

    def __init__(self, name="lookup"):
        self.name = name
        self.ran = 0
        self.func = self._work

    def _work(self, **kwargs):
        self.ran += 1
        return "result"

    def __call__(self, **kwargs):
        return self.func(**kwargs)


# ---- the LM -------------------------------------------------------------


def test_a_denied_request_never_reaches_the_provider():
    zen = FakeClient(allowed=False, reason="contains a credential")
    lm = ZentinelleLM(zen, "openai/gpt-5")

    with pytest.raises(PolicyViolationError):
        lm.forward(messages=[{"content": "here is my key"}])

    assert lm.forwarded == 0, "the provider was called despite the refusal"


def test_an_allowed_request_reaches_the_provider():
    zen = FakeClient(allowed=True)
    lm = ZentinelleLM(zen, "openai/gpt-5")

    lm.forward(messages=[{"content": "hello"}])

    assert lm.forwarded == 1


def test_a_plain_string_prompt_is_evaluated():
    zen = FakeClient()
    ZentinelleLM(zen, "openai/gpt-5").forward(prompt="the quick brown fox")

    assert "the quick brown fox" in zen.evaluated[0][1]["content"]


def test_token_usage_is_recorded():
    zen = FakeClient()
    ZentinelleLM(zen, "openai/gpt-5").forward(messages=[])

    assert zen.usage[0].input_tokens == 11
    assert zen.usage[0].output_tokens == 4
    assert zen.usage[0].model == "openai/gpt-5"


def test_an_unreachable_control_plane_refuses_by_default():
    zen = FakeClient(raises=RuntimeError("down"))
    lm = ZentinelleLM(zen, "openai/gpt-5")

    with pytest.raises(PolicyViolationError):
        lm.forward(messages=[])

    assert lm.forwarded == 0


def test_fail_open_allows_when_the_check_fails():
    zen = FakeClient(raises=RuntimeError("down"))
    lm = ZentinelleLM(zen, "openai/gpt-5", fail_open=True)

    lm.forward(messages=[])

    assert lm.forwarded == 1


def test_litellm_kwargs_reach_the_underlying_lm():
    zen = FakeClient()
    lm = ZentinelleLM(zen, "openai/gpt-5", api_base="https://gw/v1", api_key="k")

    assert lm.kwargs["api_base"] == "https://gw/v1"
    assert lm.kwargs["api_key"] == "k"


# ---- tools --------------------------------------------------------------


def test_a_denied_tool_never_runs():
    zen = FakeClient(allowed=False, reason="not on the allowlist")
    tool = governed_tool(FakeTool("delete_records"), zen)

    with pytest.raises(PolicyViolationError):
        tool(path="/etc")

    assert tool.ran == 0


def test_an_allowed_tool_runs_and_is_recorded():
    zen = FakeClient(allowed=True)
    tool = governed_tool(FakeTool(), zen)

    assert tool(q="x") == "result"
    assert ("tool_call", "lookup") in zen.events


def test_wrapping_twice_does_not_double_check():
    zen = FakeClient(allowed=True)
    tool = governed_tool(governed_tool(FakeTool(), zen), zen)

    tool(q="x")

    assert zen.tool_checks == ["lookup"]


def test_govern_tools_wraps_every_tool():
    zen = FakeClient(allowed=True)
    for tool in govern_tools([FakeTool("a"), FakeTool("b")], zen):
        tool()

    assert zen.tool_checks == ["a", "b"]


# ---- the audit callback -------------------------------------------------


def test_the_callback_records_but_cannot_refuse():
    """It is built on a dispatcher that swallows exceptions.

    Nothing here can stop a call, which is exactly why enforcement lives in
    ZentinelleLM. The test records the division so the README's claim and the
    code cannot drift apart.
    """
    zen = FakeClient()
    callback = ZentinelleCallback(zen)

    callback.on_lm_end("call-1", outputs=None)
    callback.on_tool_end("call-2", outputs=None, exception=RuntimeError("boom"))

    kinds = [e for e, _ in zen.events]
    assert "lm_call" in kinds
    assert "tool_call_observed" in kinds
    # `hasattr` would be True either way — BaseCallback defines a no-op
    # on_lm_start that every subclass inherits. What matters is whether this
    # class overrides it, which is what would imply it could block.
    assert "on_lm_start" not in type(callback).__dict__, (
        "ZentinelleCallback overrides on_lm_start. DSPy's dispatcher catches "
        "and logs whatever a callback raises and then calls the wrapped "
        "function anyway, so a start handler here would look like enforcement "
        "and be none. Enforcement belongs in ZentinelleLM."
    )
    assert "on_tool_start" not in type(callback).__dict__


def test_the_callback_never_raises():
    zen = FakeClient()
    zen.emit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no route"))

    ZentinelleCallback(zen).on_lm_end("call-1", outputs=None)


# ---- gateway routing ----------------------------------------------------


def test_gateway_kwargs_use_litellms_names():
    kwargs = gateway_lm_kwargs(gateway_url="https://gw.internal", api_key="k")

    assert kwargs["api_base"] == "https://gw.internal/proxy/openai/v1"
    assert kwargs["api_key"] == "k"
