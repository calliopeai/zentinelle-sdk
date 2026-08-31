"""Tests for the Zentinelle Google ADK plugin.

ADK is not installed. The stubs mirror the 2.8 contract, whose defining
property is that a `before_*` callback returning non-None short-circuits what
follows and its value becomes the result. So the assertions here are about
*what is returned*, not about what is raised.
"""

import sys
import types
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest


def _install_adk_stubs():
    google = sys.modules.get("google") or types.ModuleType("google")
    adk = types.ModuleType("google.adk")
    plugins = types.ModuleType("google.adk.plugins")
    models = types.ModuleType("google.adk.models")
    genai = types.ModuleType("google.genai")
    genai_types = types.ModuleType("google.genai.types")

    class BasePlugin:
        def __init__(self, name="plugin"):
            self.name = name

    @dataclass
    class Part:
        text: Optional[str] = None

    @dataclass
    class Content:
        role: str = "model"
        parts: list = field(default_factory=list)

    @dataclass
    class LlmResponse:
        content: Any = None

    plugins.BasePlugin = BasePlugin
    models.LlmResponse = LlmResponse
    genai_types.Part = Part
    genai_types.Content = Content
    genai.types = genai_types
    adk.plugins = plugins
    adk.models = models
    google.adk = adk

    sys.modules["google"] = google
    sys.modules["google.adk"] = adk
    sys.modules["google.adk.plugins"] = plugins
    sys.modules["google.adk.models"] = models
    sys.modules["google.genai"] = genai
    sys.modules["google.genai.types"] = genai_types


_install_adk_stubs()

from zentinelle_google_adk import ZentinellePlugin  # noqa: E402


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


class FakeRequest:
    def __init__(self, text="hello"):
        from google.genai.types import Content, Part

        self.contents = [Content(role="user", parts=[Part(text=text)])]


def _ctx(name="assistant"):
    return types.SimpleNamespace(agent_name=name)


def _tool(name="lookup"):
    return types.SimpleNamespace(name=name)


# ---- model requests -----------------------------------------------------


@pytest.mark.asyncio
async def test_an_allowed_request_returns_none_so_the_model_runs():
    zen = FakeClient(allowed=True)
    plugin = ZentinellePlugin(zen)

    result = await plugin.before_model_callback(
        callback_context=_ctx(), llm_request=FakeRequest()
    )

    assert result is None, "returning non-None would have blocked an allowed request"


@pytest.mark.asyncio
async def test_a_denied_request_returns_a_refusal_response():
    zen = FakeClient(allowed=False, reason="contains a credential")
    plugin = ZentinellePlugin(zen)

    result = await plugin.before_model_callback(
        callback_context=_ctx(), llm_request=FakeRequest("here is my key")
    )

    assert result is not None, "a denial that returns None lets the model run"
    assert "contains a credential" in result.content.parts[0].text


@pytest.mark.asyncio
async def test_the_prompt_text_reaches_the_policy_engine():
    zen = FakeClient()
    plugin = ZentinellePlugin(zen)

    await plugin.before_model_callback(
        callback_context=_ctx(), llm_request=FakeRequest("the quick brown fox")
    )

    assert "the quick brown fox" in zen.evaluated[0][1]["content"]


@pytest.mark.asyncio
async def test_an_unreachable_control_plane_refuses_by_default():
    zen = FakeClient(raises=RuntimeError("control plane unreachable"))
    plugin = ZentinellePlugin(zen)

    result = await plugin.before_model_callback(
        callback_context=_ctx(), llm_request=FakeRequest()
    )

    assert result is not None


@pytest.mark.asyncio
async def test_fail_open_allows_when_the_check_fails():
    zen = FakeClient(raises=RuntimeError("down"))
    plugin = ZentinellePlugin(zen, fail_open=True)

    result = await plugin.before_model_callback(
        callback_context=_ctx(), llm_request=FakeRequest()
    )

    assert result is None


# ---- usage --------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_token_counts_are_recorded():
    zen = FakeClient()
    plugin = ZentinellePlugin(zen)
    response = types.SimpleNamespace(
        usage_metadata=types.SimpleNamespace(
            prompt_token_count=200, candidates_token_count=50
        ),
        model="gemini-2.0-flash",
    )

    result = await plugin.after_model_callback(
        callback_context=_ctx(), llm_response=response
    )

    assert result is None, "returning a response here would replace the model's"
    assert zen.usage[0].input_tokens == 200
    assert zen.usage[0].output_tokens == 50


# ---- tools --------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_allowed_tool_call_returns_none():
    zen = FakeClient(allowed=True)
    plugin = ZentinellePlugin(zen)

    result = await plugin.before_tool_callback(
        tool=_tool(), tool_args={}, tool_context=None
    )

    assert result is None
    assert zen.tool_checks == ["lookup"]


@pytest.mark.asyncio
async def test_a_denied_tool_call_returns_an_error_dict():
    zen = FakeClient(allowed=False, reason="not on the allowlist")
    plugin = ZentinellePlugin(zen)

    result = await plugin.before_tool_callback(
        tool=_tool("delete_records"), tool_args={}, tool_context=None
    )

    assert isinstance(result, dict), "a non-dict return would not stop the tool"
    assert "delete_records" in result["error"]


@pytest.mark.asyncio
async def test_an_unreachable_control_plane_stops_the_tool():
    zen = FakeClient(raises=RuntimeError("down"))
    plugin = ZentinellePlugin(zen)

    result = await plugin.before_tool_callback(
        tool=_tool("wire_transfer"), tool_args={}, tool_context=None
    )

    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_a_completed_tool_call_is_recorded():
    zen = FakeClient()
    plugin = ZentinellePlugin(zen)

    result = await plugin.after_tool_callback(
        tool=_tool(), tool_args={}, tool_context=None, result={"ok": True}
    )

    assert result is None
    assert zen.events == ["lookup"]


@pytest.mark.asyncio
async def test_audit_failure_does_not_break_the_run():
    zen = FakeClient()
    zen.emit_tool_call = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("full"))
    plugin = ZentinellePlugin(zen)

    await plugin.after_tool_callback(
        tool=_tool(), tool_args={}, tool_context=None, result={}
    )
