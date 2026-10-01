"""Source and installed-wheel Copilot callbacks against the shared transport."""

import json
import os
import subprocess
import sys

import pytest

from test_pre_tool_agent_host import FakeZentinelle

EVENT = {
    "sessionId": "34a8d2c6-5543-4d3e-b0b6-35d9c4400c2f",
    "timestamp": 1790865403301,
    "cwd": "/project with spaces ' and $",
    "toolName": "bash",
    "toolArgs": {"command": "printf 'quoted $ input'", "description": "Exact native fixture"},
}


def run_hook(url, tmp_path, event=None, action="pre", extra=None, raw=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("ZENTINELLE_")}
    env.update(ZENTINELLE_ENDPOINT=url, ZENTINELLE_KEY="sk_fixture_not_real", ZENTINELLE_REQUIRED="1")
    env.update(extra or {})
    return subprocess.run([sys.executable, "-m", "zentinelle_agent.hooks.copilot", action],
                          cwd=tmp_path, env=env, input=raw if raw is not None else json.dumps(event or EVENT),
                          capture_output=True, text=True, timeout=15)


@pytest.fixture
def policy():
    fakes = []

    def make(response):
        fake = FakeZentinelle([response])
        fakes.append(fake)
        return fake

    yield make
    for fake in fakes:
        fake.close()


def test_native_allow_keeps_exact_observed_identity_without_fabricated_call(policy, tmp_path):
    fake = policy({"decision": "allow", "allowed": True})
    result = run_hook(fake.url, tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"permissionDecision": "allow"}
    assert fake.requests[0][2] == {
        "action": "tool_call",
        "context": {"source": "copilot_cli_hook", "tool": "bash", "tool_name": "bash",
                    "tool_input": EVENT["toolArgs"], "session_id": EVENT["sessionId"],
                    "timestamp": EVENT["timestamp"], "cwd": EVENT["cwd"]},
    }


@pytest.mark.parametrize("response", [
    {"decision": "deny", "allowed": False}, {"decision": "ask", "allowed": False},
    {"decision": "allow", "allowed": False}, {"allowed": True},
])
def test_only_consistent_explicit_allow_releases_native_hook(policy, tmp_path, response):
    fake = policy(response)
    result = run_hook(fake.url, tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["permissionDecision"] == "deny"
    assert len(fake.requests) == 1


@pytest.mark.parametrize("field", ["sessionId", "timestamp", "cwd", "toolName", "toolArgs"])
def test_missing_native_field_refuses_before_http(policy, tmp_path, field):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, {key: value for key, value in EVENT.items() if key != field})
    assert result.returncode == 2
    assert fake.requests == []


@pytest.mark.parametrize("field,value", [
    ("tool_call_id", "invented"), ("tool_name", "Bash"), ("session_id", "other"),
    ("hook_event_name", "PreToolUse"), ("id", "invented"),
])
def test_foreign_aliases_do_not_turn_copilot_into_another_harness(policy, tmp_path, field, value):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, {**EVENT, field: value})
    assert result.returncode == 2
    assert fake.requests == []


@pytest.mark.parametrize("field,value", [("timestamp", True), ("timestamp", -1), ("toolArgs", "{\"a\":1}")])
def test_unqualified_native_input_shape_refused(policy, tmp_path, field, value):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, {**EVENT, field: value})
    assert result.returncode == 2
    assert fake.requests == []


def test_foreign_host_identity_refused(policy, tmp_path):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, extra={"ZENTINELLE_HARNESS": "claude"})
    assert result.returncode == 2
    assert fake.requests == []


def test_duplicate_json_refused_before_http(policy, tmp_path):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, raw='{"sessionId":"a","sessionId":"b"}')
    assert result.returncode == 2
    assert fake.requests == []


def test_offline_refusal_ignores_legacy_fail_open(tmp_path):
    result = run_hook("http://127.0.0.1:1", tmp_path, extra={"ZENTINELLE_FAIL_OPEN": "1"})
    assert result.returncode == 2
    assert json.loads(result.stdout)["permissionDecision"] == "deny"


def test_required_configuration_cannot_release_hook(tmp_path):
    result = run_hook("", tmp_path, extra={"ZENTINELLE_KEY": ""})
    assert result.returncode == 2


def test_native_post_result_is_best_effort_audit(policy, tmp_path):
    fake = policy({})
    native_result = {"resultType": "success", "textResultForLlm": "<shellId: 0 completed with exit code 0>"}
    result = run_hook(fake.url, tmp_path, {**EVENT, "toolResult": native_result}, action="post")
    assert result.returncode == 0
    assert fake.requests[0][1] == "/api/zentinelle/v1/events"
    assert fake.requests[0][2]["events"][0]["payload"] == {
        "source": "copilot_cli_hook", "tool": "bash", "inputs": EVENT["toolArgs"], "outputs": native_result,
        "session_id": EVENT["sessionId"], "timestamp": EVENT["timestamp"],
    }


def test_post_offline_never_replays_or_claims_authorization(tmp_path):
    result = run_hook("http://127.0.0.1:1", tmp_path, {**EVENT, "toolResult": {}}, action="post")
    assert result.returncode == 0
    assert result.stdout == ""
