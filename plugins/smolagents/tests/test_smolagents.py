"""Tests for the Zentinelle smolagents plugin.

smolagents is not installed. The stub `Model` is bare, which is enough: the
plugin wraps a model rather than extending a concrete one.

The case worth reading is `test_a_governed_tool_is_blocked_when_called_directly`.
smolagents' `CodeAgent` puts tool objects into a Python executor's namespace and
lets the model call them, so the wrapper has to survive being invoked as a
plain callable, not only through an agent's own dispatch.
"""

import sys
import types
from dataclasses import dataclass
from typing import Optional

import pytest


def _install_smolagents_stubs():
    root = types.ModuleType("smolagents")
    models = types.ModuleType("smolagents.models")

    class Model:
        pass

    class OpenAIModel(Model):
        def __init__(self, model_id=None, api_base=None, api_key=None, **kwargs):
            self.model_id = model_id
            self.api_base = api_base
            self.api_key = api_key

    models.Model = Model
    models.OpenAIModel = OpenAIModel
    root.models = models

    sys.modules["smolagents"] = root
    sys.modules["smolagents.models"] = models


_install_smolagents_stubs()

from zentinelle_smolagents import (  # noqa: E402
    PolicyViolationError,
    ZentinelleModel,
    ZentinelleStepCallback,
    gateway_model,
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


class FakeMessage:
    def __init__(self, content="hi", input_tokens=10, output_tokens=5):
        self.content = content
        self.token_usage = types.SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens
        )


class FakeInnerModel:
    model_id = "gpt-5"
    flatten_messages_as_text = True

    def __init__(self):
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        return FakeMessage()


class FakeTool:
    """Mirrors smolagents' Tool: `__call__` delegates to `forward`."""

    name = "lookup"

    def __init__(self):
        self.ran = 0

    def forward(self, *args, **kwargs):
        self.ran += 1
        return "result"

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)


# ---- the model wrapper --------------------------------------------------


def test_a_denied_request_never_reaches_the_provider():
    zen = FakeClient(allowed=False, reason="contains a credential")
    inner = FakeInnerModel()

    with pytest.raises(PolicyViolationError):
        ZentinelleModel(inner, zen).generate([types.SimpleNamespace(content="key")])

    assert inner.calls == 0, "the provider was called despite the refusal"


def test_an_allowed_request_reaches_the_provider():
    zen = FakeClient(allowed=True)
    inner = FakeInnerModel()

    message = ZentinelleModel(inner, zen).generate(
        [types.SimpleNamespace(content="hello")]
    )

    assert inner.calls == 1
    assert message.content == "hi"


def test_calling_the_model_directly_is_also_governed():
    """Agents call `model(...)`, not only `model.generate(...)`."""
    zen = FakeClient(allowed=False, reason="no")
    inner = FakeInnerModel()

    with pytest.raises(PolicyViolationError):
        ZentinelleModel(inner, zen)([types.SimpleNamespace(content="x")])

    assert inner.calls == 0


def test_token_usage_is_recorded():
    zen = FakeClient()
    ZentinelleModel(FakeInnerModel(), zen).generate([])

    assert zen.usage[0].input_tokens == 10
    assert zen.usage[0].output_tokens == 5
    assert zen.usage[0].model == "gpt-5"


def test_unknown_attributes_fall_through_to_the_wrapped_model():
    """Agents read provider-specific attributes off the model directly."""
    governed = ZentinelleModel(FakeInnerModel(), FakeClient())

    assert governed.flatten_messages_as_text is True


def test_an_unreachable_control_plane_refuses_by_default():
    zen = FakeClient(raises=RuntimeError("down"))
    inner = FakeInnerModel()

    with pytest.raises(PolicyViolationError):
        ZentinelleModel(inner, zen).generate([])

    assert inner.calls == 0


def test_fail_open_allows_when_the_check_fails():
    zen = FakeClient(raises=RuntimeError("down"))
    inner = FakeInnerModel()

    ZentinelleModel(inner, zen, fail_open=True).generate([])

    assert inner.calls == 1


# ---- tool wrapping ------------------------------------------------------


def test_a_governed_tool_is_blocked_when_called_directly():
    """CodeAgent hands the tool to a Python executor and lets the model call it.

    Wrapping `__call__` on the instance would not survive this: Python resolves
    dunder methods on the type, so `tool(...)` would reach the original.
    """
    zen = FakeClient(allowed=False, reason="not on the allowlist")
    tool = governed_tool(FakeTool(), zen)

    with pytest.raises(PolicyViolationError):
        tool("anything")

    assert tool.ran == 0, "the tool ran despite being refused"


def test_an_allowed_tool_runs_and_is_recorded():
    zen = FakeClient(allowed=True)
    tool = governed_tool(FakeTool(), zen)

    assert tool("x") == "result"
    assert tool.ran == 1
    assert ("tool_call", "lookup") in zen.events


def test_wrapping_twice_does_not_double_check():
    zen = FakeClient(allowed=True)
    tool = governed_tool(governed_tool(FakeTool(), zen), zen)

    tool("x")

    assert zen.tool_checks == ["lookup"]


def test_govern_tools_wraps_every_tool():
    zen = FakeClient(allowed=True)
    tools = govern_tools([FakeTool(), FakeTool()], zen)

    for tool in tools:
        tool("x")

    assert zen.tool_checks == ["lookup", "lookup"]


def test_an_unreachable_control_plane_stops_the_tool():
    zen = FakeClient(raises=RuntimeError("down"))
    tool = governed_tool(FakeTool(), zen)

    with pytest.raises(PolicyViolationError):
        tool("x")

    assert tool.ran == 0


# ---- the audit callback -------------------------------------------------


def test_the_step_callback_records_a_step():
    zen = FakeClient()
    callback = ZentinelleStepCallback(zen)
    step = types.SimpleNamespace(
        step_number=3, token_usage=types.SimpleNamespace(input_tokens=7, output_tokens=2)
    )

    callback(step, agent=types.SimpleNamespace(name="coder"))

    event, payload = zen.events[0]
    assert event == "agent_step"
    assert payload["step_number"] == 3
    assert payload["agent"] == "coder"


def test_the_step_callback_never_raises():
    """It runs inside the agent loop and only exists to write things down."""
    zen = FakeClient()
    zen.emit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no route"))

    ZentinelleStepCallback(zen)(types.SimpleNamespace(step_number=1))


# ---- gateway routing ----------------------------------------------------


def test_gateway_model_uses_the_api_base_kwarg():
    """smolagents names it api_base on OpenAIModel, not base_url."""
    model = gateway_model("gpt-5", gateway_url="https://gw.internal", api_key="k")

    assert model.api_base == "https://gw.internal/proxy/openai/v1"
    assert model.model_id == "gpt-5"
