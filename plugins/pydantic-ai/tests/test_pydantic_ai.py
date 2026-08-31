"""Tests for the Zentinelle Pydantic AI plugin.

Pydantic AI is not installed; the tests build enough of the module tree for the
plugin's imports to resolve, matching every other plugin in this repo. The
stubs mirror the real 2.36 signatures.

What is checked is the enforcement: a refused request does not reach the model,
a refused tool does not run, and an unreachable control plane refuses rather
than waves things through.
"""

import sys
import types
from dataclasses import dataclass
from typing import Any, Optional

import pytest


def _install_pydantic_ai_stubs():
    root = types.ModuleType("pydantic_ai")
    capabilities = types.ModuleType("pydantic_ai.capabilities")
    messages = types.ModuleType("pydantic_ai.messages")

    class AbstractCapability:
        pass

    class SkipModelRequest(Exception):
        def __init__(self, response):
            super().__init__("skip")
            self.response = response

    class SkipToolExecution(Exception):
        def __init__(self, result):
            super().__init__("skip")
            self.result = result

    @dataclass
    class TextPart:
        content: str

    @dataclass
    class ModelResponse:
        parts: list

    capabilities.AbstractCapability = AbstractCapability
    messages.ModelResponse = ModelResponse
    messages.TextPart = TextPart
    root.SkipModelRequest = SkipModelRequest
    root.SkipToolExecution = SkipToolExecution
    root.capabilities = capabilities
    root.messages = messages

    sys.modules["pydantic_ai"] = root
    sys.modules["pydantic_ai.capabilities"] = capabilities
    sys.modules["pydantic_ai.messages"] = messages
    return root


_install_pydantic_ai_stubs()

from zentinelle_pydantic_ai import (  # noqa: E402
    PolicyViolationError,
    ZentinelleCapability,
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


class FakeRequestContext:
    def __init__(self, messages=None):
        self.messages = messages or []


def _tool(name="lookup"):
    return types.SimpleNamespace(name=name)


# ---- model requests -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_denied_request_never_reaches_the_model():
    zen = FakeClient(allowed=False, reason="contains a credential")
    capability = ZentinelleCapability(zen)

    with pytest.raises(PolicyViolationError) as excinfo:
        await capability.before_model_request(None, FakeRequestContext())

    assert "contains a credential" in str(excinfo.value)


@pytest.mark.asyncio
async def test_an_allowed_request_passes_the_context_through():
    zen = FakeClient(allowed=True)
    capability = ZentinelleCapability(zen)
    ctx = FakeRequestContext()

    assert await capability.before_model_request(None, ctx) is ctx


@pytest.mark.asyncio
async def test_substitute_mode_uses_the_frameworks_own_skip():
    """The soft refusal is opt-in, and uses Pydantic AI's mechanism."""
    from pydantic_ai import SkipModelRequest

    zen = FakeClient(allowed=False, reason="nope")
    capability = ZentinelleCapability(zen, on_denial="substitute")

    with pytest.raises(SkipModelRequest):
        await capability.before_model_request(None, FakeRequestContext())


def test_on_denial_is_validated_at_construction():
    with pytest.raises(ValueError):
        ZentinelleCapability(FakeClient(), on_denial="maybe")


@pytest.mark.asyncio
async def test_an_unreachable_control_plane_refuses_by_default():
    zen = FakeClient(raises=RuntimeError("control plane unreachable"))
    capability = ZentinelleCapability(zen)

    with pytest.raises(PolicyViolationError):
        await capability.before_model_request(None, FakeRequestContext())


@pytest.mark.asyncio
async def test_fail_open_allows_when_the_check_fails():
    zen = FakeClient(raises=RuntimeError("control plane unreachable"))
    capability = ZentinelleCapability(zen, fail_open=True)
    ctx = FakeRequestContext()

    assert await capability.before_model_request(None, ctx) is ctx


# ---- tools --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_denied_tool_call_stops_the_run():
    zen = FakeClient(allowed=False, reason="not on the allowlist")
    capability = ZentinelleCapability(zen)

    with pytest.raises(PolicyViolationError) as excinfo:
        await capability.before_tool_execute(
            None, call=None, tool_def=_tool("delete_records"), args={}
        )

    assert "delete_records" in str(excinfo.value)


@pytest.mark.asyncio
async def test_an_allowed_tool_call_returns_its_args_unchanged():
    zen = FakeClient(allowed=True)
    capability = ZentinelleCapability(zen)
    args = {"q": "hello"}

    result = await capability.before_tool_execute(
        None, call=None, tool_def=_tool(), args=args
    )

    assert result is args
    assert zen.tool_checks == ["lookup"]


@pytest.mark.asyncio
async def test_an_unreachable_control_plane_stops_the_tool():
    zen = FakeClient(raises=RuntimeError("down"))
    capability = ZentinelleCapability(zen)

    with pytest.raises(PolicyViolationError):
        await capability.before_tool_execute(
            None, call=None, tool_def=_tool("wire_transfer"), args={}
        )


@pytest.mark.asyncio
async def test_a_completed_tool_call_is_recorded():
    zen = FakeClient()
    capability = ZentinelleCapability(zen)

    out = await capability.after_tool_execute(
        None, call=None, tool_def=_tool(), args={}, result="done"
    )

    assert out == "done"
    assert zen.events == ["lookup"]


# ---- usage --------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_usage_is_recorded():
    zen = FakeClient()
    capability = ZentinelleCapability(zen)
    response = types.SimpleNamespace(
        usage=types.SimpleNamespace(input_tokens=120, output_tokens=45),
        model_name="gpt-5",
    )

    out = await capability.after_model_request(
        None, request_context=None, response=response
    )

    assert out is response
    assert zen.usage[0].input_tokens == 120
    assert zen.usage[0].output_tokens == 45


@pytest.mark.asyncio
async def test_a_response_without_usage_records_nothing():
    zen = FakeClient()
    capability = ZentinelleCapability(zen)

    await capability.after_model_request(
        None, request_context=None, response=types.SimpleNamespace(usage=None)
    )

    assert zen.usage == []


@pytest.mark.asyncio
async def test_a_usage_buffer_failure_does_not_break_the_run():
    zen = FakeClient()
    zen.track_usage = lambda usage: (_ for _ in ()).throw(RuntimeError("full"))
    capability = ZentinelleCapability(zen)
    response = types.SimpleNamespace(
        usage=types.SimpleNamespace(input_tokens=1, output_tokens=1), model_name="m"
    )

    await capability.after_model_request(
        None, request_context=None, response=response
    )
