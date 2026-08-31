"""Tests for the Zentinelle Agno plugin.

Agno is not installed; the stubs mirror the real 3.0 contract. The one that
matters is `InputCheckError` / `OutputCheckError`: Agno catches and logs every
other exception a hook raises, so raising anything else looks like enforcement
while the run carries on.
"""

import sys
import types
from dataclasses import dataclass
from typing import Optional

import pytest


def _install_agno_stubs():
    root = types.ModuleType("agno")
    exceptions = types.ModuleType("agno.exceptions")

    class InputCheckError(Exception):
        pass

    class OutputCheckError(Exception):
        pass

    exceptions.InputCheckError = InputCheckError
    exceptions.OutputCheckError = OutputCheckError
    root.exceptions = exceptions

    sys.modules["agno"] = root
    sys.modules["agno.exceptions"] = exceptions
    return exceptions


_agno_exceptions = _install_agno_stubs()

from zentinelle_agno import PolicyViolationError, ZentinelleGuard  # noqa: E402


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


# ---- input --------------------------------------------------------------


def test_a_denied_input_stops_the_run():
    zen = FakeClient(allowed=False, reason="contains a credential")
    guard = ZentinelleGuard(zen)

    with pytest.raises(_agno_exceptions.InputCheckError) as excinfo:
        guard.pre_hook(run_input="here is my key")

    assert "contains a credential" in str(excinfo.value)


def test_an_allowed_input_proceeds():
    zen = FakeClient(allowed=True)
    guard = ZentinelleGuard(zen)

    guard.pre_hook(run_input="hello")

    assert zen.evaluated[0][0] == "model_request"


def test_a_failed_check_raises_agnos_own_error_not_a_plugin_one():
    """Anything else would be swallowed and logged, and the run would go on.

    This is the whole reason the plugin raises framework exceptions: a
    fail-closed path that Agno catches is not fail-closed.
    """
    zen = FakeClient(raises=RuntimeError("control plane unreachable"))
    guard = ZentinelleGuard(zen)

    with pytest.raises(_agno_exceptions.InputCheckError):
        guard.pre_hook(run_input="hello")


def test_fail_open_allows_when_the_check_fails():
    zen = FakeClient(raises=RuntimeError("down"))
    guard = ZentinelleGuard(zen, fail_open=True)

    guard.pre_hook(run_input="hello")


# ---- output -------------------------------------------------------------


def test_a_denied_output_stops_the_run():
    zen = FakeClient(allowed=False, reason="leaks a hostname")
    guard = ZentinelleGuard(zen)

    with pytest.raises(_agno_exceptions.OutputCheckError):
        guard.post_hook(run_output=types.SimpleNamespace(content="db-01", metrics=None))


def test_token_usage_is_recorded_from_the_run_output():
    zen = FakeClient()
    guard = ZentinelleGuard(zen)
    output = types.SimpleNamespace(
        content="done",
        metrics=types.SimpleNamespace(input_tokens=90, output_tokens=12),
        model="gpt-5",
    )

    guard.post_hook(run_output=output)

    assert zen.usage[0].input_tokens == 90
    assert zen.usage[0].output_tokens == 12


# ---- tools --------------------------------------------------------------


def _func(**kwargs):
    return "ran"


def test_a_denied_tool_never_runs():
    zen = FakeClient(allowed=False, reason="not on the allowlist")
    guard = ZentinelleGuard(zen)
    calls = []

    def func(**kwargs):
        calls.append(kwargs)
        return "ran"

    with pytest.raises(PolicyViolationError):
        guard.tool_hook("delete_records", func, {})

    assert calls == [], "the tool ran despite being refused"


def test_an_allowed_tool_runs_and_is_recorded():
    zen = FakeClient(allowed=True)
    guard = ZentinelleGuard(zen)

    assert guard.tool_hook("lookup", _func, {"q": "x"}) == "ran"
    assert zen.tool_checks == ["lookup"]
    assert zen.events == ["lookup"]


def test_an_unreachable_control_plane_stops_the_tool():
    zen = FakeClient(raises=RuntimeError("down"))
    guard = ZentinelleGuard(zen)
    calls = []

    with pytest.raises(PolicyViolationError):
        guard.tool_hook("wire_transfer", lambda **k: calls.append(k), {})

    assert calls == []


def test_fail_open_lets_the_tool_run():
    zen = FakeClient(raises=RuntimeError("down"))
    guard = ZentinelleGuard(zen, fail_open=True)

    assert guard.tool_hook("lookup", _func, {}) == "ran"


def test_audit_failure_does_not_break_the_tool_call():
    zen = FakeClient()
    zen.emit_tool_call = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("full"))
    guard = ZentinelleGuard(zen)

    assert guard.tool_hook("lookup", _func, {}) == "ran"
