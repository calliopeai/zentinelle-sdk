"""Tests for the Zentinelle BeeAI Framework plugin.

BeeAI is not installed. The stub emitter reproduces the property the whole
integration rests on: `_invoke` re-raises what a listener throws rather than
logging it, so a `"start"` listener can stop the call. If that ever stopped
being true the tests here would still pass while the plugin governed nothing,
so `test_the_emitter_contract_this_relies_on` pins the assumption explicitly.
"""

import asyncio
import types
from dataclasses import dataclass
from typing import Optional

import pytest

from zentinelle_bee_agent import PolicyViolationError, ZentinelleGuard


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


class FakeEmitter:
    """Mirrors BeeAI's Emitter: listeners run, and their exceptions propagate."""

    def __init__(self):
        self.listeners = []

    def on(self, matcher, callback):
        self.listeners.append((matcher, callback))
        return lambda: None

    async def emit(self, name, data, path=None):
        meta = types.SimpleNamespace(name=name, path=path or name, creator=None)
        for matcher, callback in self.listeners:
            if matcher in (name, "*.*"):
                await callback(data, meta)


def _event(name="start", path="tool.lookup.start", creator=None):
    return types.SimpleNamespace(name=name, path=path, creator=creator)


def _start_data(text="hello"):
    return types.SimpleNamespace(
        input=[types.SimpleNamespace(text=text)]
    )


# ---- model requests -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_denied_request_raises_from_the_start_listener():
    zen = FakeClient(allowed=False, reason="contains a credential")
    guard = ZentinelleGuard(zen)

    with pytest.raises(PolicyViolationError) as excinfo:
        await guard.on_model_start(_start_data("my key"))

    assert "contains a credential" in str(excinfo.value)


@pytest.mark.asyncio
async def test_an_allowed_request_returns_quietly():
    zen = FakeClient(allowed=True)

    await ZentinelleGuard(zen).on_model_start(_start_data())

    assert zen.evaluated[0][0] == "model_request"


@pytest.mark.asyncio
async def test_the_prompt_text_reaches_the_policy_engine():
    zen = FakeClient()

    await ZentinelleGuard(zen).on_model_start(_start_data("the quick brown fox"))

    assert "the quick brown fox" in zen.evaluated[0][1]["content"]


@pytest.mark.asyncio
async def test_an_unreachable_control_plane_refuses_by_default():
    zen = FakeClient(raises=RuntimeError("down"))

    with pytest.raises(PolicyViolationError):
        await ZentinelleGuard(zen).on_model_start(_start_data())


@pytest.mark.asyncio
async def test_fail_open_allows_when_the_check_fails():
    zen = FakeClient(raises=RuntimeError("down"))

    await ZentinelleGuard(zen, fail_open=True).on_model_start(_start_data())


# ---- tools --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_denied_tool_raises_before_it_runs():
    zen = FakeClient(allowed=False, reason="not on the allowlist")
    guard = ZentinelleGuard(zen)

    with pytest.raises(PolicyViolationError) as excinfo:
        await guard.on_tool_start(None, _event(path="tool.delete_records.start"))

    assert "delete_records" in str(excinfo.value)


@pytest.mark.asyncio
async def test_the_tool_name_prefers_the_event_creator():
    zen = FakeClient(allowed=True)
    guard = ZentinelleGuard(zen)
    creator = types.SimpleNamespace(name="from_creator")

    await guard.on_tool_start(None, _event(creator=creator))

    assert zen.tool_checks == ["from_creator"]


@pytest.mark.asyncio
async def test_the_tool_name_falls_back_to_the_event_path():
    zen = FakeClient(allowed=True)

    await ZentinelleGuard(zen).on_tool_start(None, _event(path="tool.lookup.start"))

    assert zen.tool_checks == ["lookup"]


@pytest.mark.asyncio
async def test_an_allowed_tool_is_recorded():
    zen = FakeClient(allowed=True)

    await ZentinelleGuard(zen).on_tool_start(None, _event())

    assert ("tool_call", "lookup") in zen.events


# ---- usage --------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_usage_is_read_from_the_success_event():
    zen = FakeClient()
    data = types.SimpleNamespace(
        value=types.SimpleNamespace(
            usage=types.SimpleNamespace(prompt_tokens=30, completion_tokens=7),
            model="gpt-5",
        )
    )

    await ZentinelleGuard(zen).on_model_success(data)

    assert zen.usage[0].input_tokens == 30
    assert zen.usage[0].output_tokens == 7


# ---- subscription -------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_agent_routes_model_and_tool_events():
    zen = FakeClient(allowed=True)
    agent = types.SimpleNamespace(emitter=FakeEmitter())

    ZentinelleGuard(zen).attach_agent(agent)

    await agent.emitter.emit("start", _start_data(), path="backend.openai.chat.start")
    await agent.emitter.emit("start", None, path="tool.lookup.start")

    assert zen.evaluated, "the model event was not routed to the model check"
    assert zen.tool_checks == ["lookup"], "the tool event was not routed"


@pytest.mark.asyncio
async def test_the_emitter_contract_this_relies_on():
    """A raising listener must abort the emit, or nothing here enforces.

    BeeAI wraps a listener's exception as an EmitterError and re-raises it
    inside a TaskGroup rather than logging and continuing. Every other
    framework in this repo that looked like it had blocking events turned out
    to swallow them, so the assumption is worth stating as a test.
    """
    emitter = FakeEmitter()
    zen = FakeClient(allowed=False, reason="no")
    guard = ZentinelleGuard(zen)
    emitter.on("start", guard.on_model_start)

    with pytest.raises(PolicyViolationError):
        await emitter.emit("start", _start_data(), path="backend.openai.chat.start")


@pytest.mark.asyncio
async def test_attach_model_subscribes_start_and_success():
    zen = FakeClient(allowed=True)
    model = types.SimpleNamespace(emitter=FakeEmitter())

    ZentinelleGuard(zen).attach_model(model)

    names = [m for m, _ in model.emitter.listeners]
    assert "start" in names
    assert "success" in names


@pytest.mark.asyncio
async def test_evaluation_can_be_turned_off():
    zen = FakeClient(allowed=False, reason="no")
    guard = ZentinelleGuard(zen, evaluate_requests=False, evaluate_tool_calls=False)

    await guard.on_model_start(_start_data())
    await guard.on_tool_start(None, _event())

    assert zen.evaluated == []
    assert zen.tool_checks == []
