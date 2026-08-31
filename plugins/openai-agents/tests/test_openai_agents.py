"""Tests for the Zentinelle OpenAI Agents SDK governance plugin.

The Agents SDK is never installed here, matching the other plugins in this
repo: the tests build just enough of the module tree for the plugin's imports
to resolve. The stubs mirror the real signatures in openai-agents 0.22.

What is actually being checked is the enforcement, not the plumbing: a denied
request must not reach the provider, and a denied tool must not run.
"""

import sys
import types
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import pytest


# ---------------------------------------------------------------------------
# Fake `agents` and `openai` modules
# ---------------------------------------------------------------------------


def _install_agents_stubs():
    agents_mod = types.ModuleType("agents")

    @dataclass
    class GuardrailFunctionOutput:
        output_info: Any
        tripwire_triggered: bool

    @dataclass
    class InputGuardrail:
        guardrail_function: Callable
        name: Optional[str] = None
        run_in_parallel: bool = True

    @dataclass
    class OutputGuardrail:
        guardrail_function: Callable
        name: Optional[str] = None

    calls = {"default_client": None, "use_for_tracing": None,
             "processors": None, "added": [], "tracing_disabled": None}

    def set_default_openai_client(client, use_for_tracing=True):
        calls["default_client"] = client
        calls["use_for_tracing"] = use_for_tracing

    def set_trace_processors(processors):
        calls["processors"] = processors

    def add_trace_processor(processor):
        calls["added"].append(processor)

    def set_tracing_disabled(disabled):
        calls["tracing_disabled"] = disabled

    agents_mod.GuardrailFunctionOutput = GuardrailFunctionOutput
    agents_mod.InputGuardrail = InputGuardrail
    agents_mod.OutputGuardrail = OutputGuardrail
    agents_mod.set_default_openai_client = set_default_openai_client
    agents_mod.set_trace_processors = set_trace_processors
    agents_mod.add_trace_processor = add_trace_processor
    agents_mod.set_tracing_disabled = set_tracing_disabled
    agents_mod._calls = calls

    sys.modules["agents"] = agents_mod
    return agents_mod


def _install_openai_stub():
    openai_mod = types.ModuleType("openai")

    class AsyncOpenAI:
        def __init__(self, base_url=None, api_key=None, **kwargs):
            self.base_url = base_url
            self.api_key = api_key
            self.kwargs = kwargs

    openai_mod.AsyncOpenAI = AsyncOpenAI
    sys.modules["openai"] = openai_mod
    return openai_mod


_install_agents_stubs()
_install_openai_stub()

from zentinelle_openai_agents import (  # noqa: E402
    PolicyViolationError,
    ZentinelleGuardrailError,
    ZentinelleRunHooks,
    ZentinelleTracingProcessor,
    configure,
    gateway_base_url,
    gateway_client,
    zentinelle_input_guardrail,
    zentinelle_output_guardrail,
)


# ---------------------------------------------------------------------------
# Fakes for the Zentinelle client and the SDK objects passed to hooks
# ---------------------------------------------------------------------------


@dataclass
class FakeResult:
    allowed: bool
    reason: Optional[str] = None
    policies_evaluated: list = field(default_factory=list)

    def is_fail_open(self):
        return False

    @property
    def blocked_policies(self):
        return [p["name"] for p in self.policies_evaluated if not p.get("passed", True)]


class FakeClient:
    def __init__(self, allowed=True, reason=None, raises=None):
        self.allowed = allowed
        self.reason = reason
        self.raises = raises
        self.evaluated = []
        self.tool_checks = []
        self.events = []
        self.usage = []
        self.flushed = 0

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

    def emit(self, event_type, payload=None, category=None, user_id=None):
        self.events.append((event_type, payload or {}))

    def emit_tool_call(self, tool_name, user_id=None, inputs=None, outputs=None,
                       duration_ms=None):
        self.events.append(("tool_call", {"tool": tool_name, "duration_ms": duration_ms}))

    def track_usage(self, usage):
        self.usage.append(usage)

    def flush_events(self):
        self.flushed += 1


class FakeAgent:
    def __init__(self, name="assistant", model="gpt-5"):
        self.name = name
        self.model = model


class FakeTool:
    def __init__(self, name="lookup"):
        self.name = name


# ---------------------------------------------------------------------------
# Proxy configuration
# ---------------------------------------------------------------------------


def test_base_url_names_the_provider_and_supplies_v1():
    assert gateway_base_url("https://gw.internal") == "https://gw.internal/proxy/openai/v1"


def test_base_url_tolerates_a_trailing_slash():
    # Without the strip this produces `//proxy`, which the gateway's prefix
    # match does not recognise, and every call goes unrouted.
    assert gateway_base_url("https://gw.internal/") == "https://gw.internal/proxy/openai/v1"


def test_gateway_url_is_required():
    with pytest.raises(ValueError):
        gateway_client(api_key="sk_agent_x")


def test_configure_installs_the_gateway_client():
    import agents

    client = configure(gateway_url="https://gw.internal", api_key="sk_agent_x")

    assert client.base_url == "https://gw.internal/proxy/openai/v1"
    assert agents._calls["default_client"] is client


def test_traces_do_not_go_to_openai_by_default():
    """The default must not export prompts to a third party.

    A GRC deployment exists to keep agent traffic inside a boundary. Shipping
    the same prompts and tool arguments to OpenAI's trace store by default
    would undo that without the operator ever choosing it.
    """
    import agents

    zen = FakeClient()
    configure(gateway_url="https://gw.internal", zentinelle_client=zen)

    assert agents._calls["use_for_tracing"] is False
    # The OpenAI exporter is replaced, not supplemented.
    assert len(agents._calls["processors"]) == 1
    assert isinstance(agents._calls["processors"][0], ZentinelleTracingProcessor)


def test_tracing_is_switched_off_when_there_is_nowhere_to_send_spans():
    import agents

    agents._calls["tracing_disabled"] = None
    configure(gateway_url="https://gw.internal")

    assert agents._calls["tracing_disabled"] is True


def test_opting_in_to_openai_tracing_adds_rather_than_replaces():
    import agents

    agents._calls["added"] = []
    zen = FakeClient()
    configure(
        gateway_url="https://gw.internal",
        zentinelle_client=zen,
        send_traces_to_openai=True,
    )

    assert agents._calls["use_for_tracing"] is True
    assert len(agents._calls["added"]) == 1


# ---------------------------------------------------------------------------
# Guardrails: the SDK's only halting point
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denied_input_trips_the_guardrail():
    zen = FakeClient(allowed=False, reason="contains a credential")
    guardrail = zentinelle_input_guardrail(zen)

    output = await guardrail.guardrail_function(None, FakeAgent(), "here is my key")

    assert output.tripwire_triggered is True
    assert output.output_info["reason"] == "contains a credential"


@pytest.mark.asyncio
async def test_allowed_input_does_not_trip():
    zen = FakeClient(allowed=True)
    guardrail = zentinelle_input_guardrail(zen)

    output = await guardrail.guardrail_function(None, FakeAgent(), "hello")

    assert output.tripwire_triggered is False


def test_the_input_guardrail_runs_before_the_agent():
    """Enforcement cannot run alongside the thing it is meant to prevent.

    The SDK's default is to run a guardrail in parallel with the agent, which
    is fine for scoring and wrong here: by the time a denial arrives the model
    call has been made and any tool it triggered has already run.
    """
    guardrail = zentinelle_input_guardrail(FakeClient())

    assert guardrail.run_in_parallel is False


@pytest.mark.asyncio
async def test_a_failed_check_refuses_by_default():
    zen = FakeClient(raises=RuntimeError("control plane unreachable"))
    guardrail = zentinelle_input_guardrail(zen)

    with pytest.raises(ZentinelleGuardrailError):
        await guardrail.guardrail_function(None, FakeAgent(), "hello")


@pytest.mark.asyncio
async def test_a_failed_check_allows_when_fail_open_is_set():
    zen = FakeClient(raises=RuntimeError("control plane unreachable"))
    guardrail = zentinelle_input_guardrail(zen, fail_open=True)

    output = await guardrail.guardrail_function(None, FakeAgent(), "hello")

    assert output.tripwire_triggered is False


@pytest.mark.asyncio
async def test_the_output_guardrail_checks_the_final_output():
    zen = FakeClient(allowed=False, reason="leaks an internal hostname")
    guardrail = zentinelle_output_guardrail(zen)

    output = await guardrail.guardrail_function(None, FakeAgent(), "the host is db-01")

    assert output.tripwire_triggered is True
    assert zen.evaluated[0][0] == "model_response"


@pytest.mark.asyncio
async def test_conversation_history_is_summarised_not_shipped_whole():
    """A long run must not post its entire history on every check."""
    zen = FakeClient()
    guardrail = zentinelle_input_guardrail(zen)
    history = [{"content": f"turn {i}"} for i in range(50)]

    await guardrail.guardrail_function(None, FakeAgent(), history)

    content = zen.evaluated[0][1]["content"]
    assert "turn 49" in content
    assert "turn 10" not in content


# ---------------------------------------------------------------------------
# Hooks: tool governance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_denied_tool_call_stops_the_run():
    zen = FakeClient(allowed=False, reason="not on the allowlist")
    hooks = ZentinelleRunHooks(zen)

    with pytest.raises(PolicyViolationError) as excinfo:
        await hooks.on_tool_start(None, FakeAgent(), FakeTool("delete_records"))

    assert "delete_records" in str(excinfo.value)
    assert "not on the allowlist" in str(excinfo.value)


@pytest.mark.asyncio
async def test_an_allowed_tool_call_proceeds():
    zen = FakeClient(allowed=True)
    hooks = ZentinelleRunHooks(zen)

    await hooks.on_tool_start(None, FakeAgent(), FakeTool("lookup"))

    assert zen.tool_checks == ["lookup"]


@pytest.mark.asyncio
async def test_an_unreachable_control_plane_stops_the_tool_by_default():
    zen = FakeClient(raises=RuntimeError("control plane unreachable"))
    hooks = ZentinelleRunHooks(zen)

    with pytest.raises(PolicyViolationError):
        await hooks.on_tool_start(None, FakeAgent(), FakeTool("wire_transfer"))


@pytest.mark.asyncio
async def test_fail_open_lets_the_tool_run_when_the_check_fails():
    zen = FakeClient(raises=RuntimeError("control plane unreachable"))
    hooks = ZentinelleRunHooks(zen, fail_open=True)

    await hooks.on_tool_start(None, FakeAgent(), FakeTool("lookup"))


@pytest.mark.asyncio
async def test_the_tool_name_is_read_from_the_tool_context_when_present():
    """Function tools pass a ToolContext, and it names the call being made."""
    zen = FakeClient()
    hooks = ZentinelleRunHooks(zen)
    context = types.SimpleNamespace(tool_name="from_context")

    await hooks.on_tool_start(context, FakeAgent(), FakeTool("from_tool"))

    assert zen.tool_checks == ["from_context"]


@pytest.mark.asyncio
async def test_a_tool_call_is_recorded_with_its_duration():
    zen = FakeClient()
    hooks = ZentinelleRunHooks(zen)
    context = types.SimpleNamespace(tool_name="lookup")

    await hooks.on_tool_start(context, FakeAgent(), FakeTool("lookup"))
    await hooks.on_tool_end(context, FakeAgent(), FakeTool("lookup"), "result")

    recorded = [e for e in zen.events if e[0] == "tool_call"]
    assert len(recorded) == 1
    assert recorded[0][1]["duration_ms"] is not None


@pytest.mark.asyncio
async def test_audit_failure_does_not_break_the_run():
    """Telemetry is best-effort; an agent must not die because a buffer did."""
    zen = FakeClient()
    zen.emit_tool_call = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("buffer full"))
    hooks = ZentinelleRunHooks(zen)

    await hooks.on_tool_end(types.SimpleNamespace(), FakeAgent(), FakeTool(), "ok")


# ---------------------------------------------------------------------------
# Hooks: token accounting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_usage_is_recorded_from_the_model_response():
    zen = FakeClient()
    hooks = ZentinelleRunHooks(zen)
    response = types.SimpleNamespace(
        usage=types.SimpleNamespace(input_tokens=120, output_tokens=45)
    )

    await hooks.on_llm_end(None, FakeAgent(model="gpt-5"), response)

    assert len(zen.usage) == 1
    assert zen.usage[0].input_tokens == 120
    assert zen.usage[0].output_tokens == 45
    assert zen.usage[0].model == "gpt-5"


@pytest.mark.asyncio
async def test_a_response_without_usage_records_nothing():
    zen = FakeClient()
    hooks = ZentinelleRunHooks(zen)

    await hooks.on_llm_end(None, FakeAgent(), types.SimpleNamespace(usage=None))

    assert zen.usage == []


@pytest.mark.asyncio
async def test_a_handoff_is_recorded():
    zen = FakeClient()
    hooks = ZentinelleRunHooks(zen)

    await hooks.on_handoff(None, FakeAgent("triage"), FakeAgent("billing"))

    handoffs = [e for e in zen.events if e[0] == "agent_handoff"]
    assert handoffs[0][1]["from"] == "triage"
    assert handoffs[0][1]["to"] == "billing"


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------


class FakeSpanData:
    type = "function"

    def __init__(self):
        self.name = "lookup"
        self.input = "the customer's account number is 4111 1111 1111 1111"
        self.output = "found"

    def export(self):
        return {"type": self.type, "name": self.name, "input": self.input,
                "output": self.output}


class FakeSpan:
    def __init__(self, error=None):
        self.trace_id = "trace_1"
        self.span_id = "span_1"
        self.parent_id = None
        self.started_at = "2026-08-31T00:00:00Z"
        self.ended_at = "2026-08-31T00:00:01Z"
        self.span_data = FakeSpanData()
        self.error = error


def test_span_content_is_not_recorded_by_default():
    """The audit trail records the shape of a run, not a second copy of the data."""
    zen = FakeClient()
    processor = ZentinelleTracingProcessor(zen)

    processor.on_span_end(FakeSpan())

    payload = zen.events[0][1]
    assert payload["name"] == "lookup"
    assert payload["span_type"] == "function"
    assert "input" not in payload
    assert "4111" not in str(payload)


def test_span_content_is_recorded_when_asked_for():
    zen = FakeClient()
    processor = ZentinelleTracingProcessor(zen, include_span_data=True)

    processor.on_span_end(FakeSpan())

    assert "4111" in str(zen.events[0][1])


def test_a_span_error_is_always_recorded():
    zen = FakeClient()
    processor = ZentinelleTracingProcessor(zen)

    processor.on_span_end(FakeSpan(error=types.SimpleNamespace(message="tool timed out")))

    assert zen.events[0][1]["error"] == "tool timed out"


def test_a_broken_client_does_not_break_the_agent():
    """The SDK calls these synchronously inside the run."""
    zen = FakeClient()
    zen.emit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no route to host"))
    processor = ZentinelleTracingProcessor(zen)

    processor.on_trace_start(types.SimpleNamespace(trace_id="t", name="w"))
    processor.on_span_end(FakeSpan())
    processor.on_trace_end(types.SimpleNamespace(trace_id="t", name="w"))


def test_shutdown_flushes_buffered_events():
    zen = FakeClient()
    processor = ZentinelleTracingProcessor(zen)

    processor.force_flush()
    processor.shutdown()

    assert zen.flushed == 2
