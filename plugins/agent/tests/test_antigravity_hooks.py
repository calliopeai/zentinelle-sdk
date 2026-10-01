"""Actual Antigravity native identity and strict shared policy/audit contracts."""

import json
import os
import subprocess
import sys

import pytest

from test_pre_tool_agent_host import FakeZentinelle

EVENT = {
    "conversationId": "d58ccd21-14ad-4b49-bb5f-5b81b9c2bf4a",
    "stepIdx": 2,
    "toolCall": {"name": "run_command", "args": {"CommandLine": "printf 'quoted $ input'", "Cwd": "/project",
                                                "WaitMsBeforeAsync": 5000, "toolSummary": "Fixture write",
                                                "toolAction": "Writing fixture"}},
    "workspacePaths": ["/project with spaces ' and $"],
    "transcriptPath": "/private/brain/d58ccd21-14ad-4b49-bb5f-5b81b9c2bf4a/logs/transcript_full.jsonl",
    "artifactDirectoryPath": "/private/brain/d58ccd21-14ad-4b49-bb5f-5b81b9c2bf4a",
    "modelName": "gemini-3.6-flash-medium",
}
METADATA = {name: EVENT[name] for name in ("conversationId", "stepIdx", "workspacePaths", "transcriptPath",
                                         "artifactDirectoryPath", "modelName")}


def run_hook(url, tmp_path, event=None, action="pre", extra=None, raw=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("ZENTINELLE_")}
    env.update(ZENTINELLE_ENDPOINT=url, ZENTINELLE_KEY="sk_fixture_not_real", ZENTINELLE_REQUIRED="1")
    env.update(extra or {})
    return subprocess.run([sys.executable, "-m", "zentinelle_agent.hooks.antigravity", action],
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


def test_allow_preserves_native_identity_and_continues_native_permission(policy, tmp_path):
    fake = policy({"decision": "allow", "allowed": True})
    result = run_hook(fake.url, tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"decision": "ask"}
    assert fake.requests[0][2] == {
        "action": "tool_call",
        "context": {"source": "antigravity_cli_hook", "tool": "run_command", "tool_name": "run_command",
                    "tool_input": EVENT["toolCall"]["args"], "session_id": EVENT["conversationId"], **METADATA},
    }


@pytest.mark.parametrize("response", [
    {"decision": "deny", "allowed": False}, {"decision": "ask", "allowed": False},
    {"decision": "allow", "allowed": False}, {"allowed": True},
])
def test_only_consistent_explicit_allow_releases_policy_gate(policy, tmp_path, response):
    fake = policy(response)
    result = run_hook(fake.url, tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["decision"] == "deny"
    assert len(fake.requests) == 1


@pytest.mark.parametrize("field", list(EVENT))
def test_missing_native_field_refuses_before_http(policy, tmp_path, field):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, {key: value for key, value in EVENT.items() if key != field})
    assert result.returncode == 2
    assert fake.requests == []


@pytest.mark.parametrize("field,value", [
    ("tool_call_id", "invented"), ("tool_name", "Bash"), ("session_id", "other"),
    ("hook_event_name", "PreToolUse"), ("id", "invented"), ("harness", "claude"),
])
def test_foreign_aliases_do_not_relabel_native_callback(policy, tmp_path, field, value):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, {**EVENT, field: value})
    assert result.returncode == 2
    assert fake.requests == []


@pytest.mark.parametrize("field,value", [
    ("conversationId", "not-a-uuid"), ("stepIdx", True), ("stepIdx", -1), ("workspacePaths", []),
    ("workspacePaths", ["relative"]), ("transcriptPath", "relative"), ("artifactDirectoryPath", "/bad\npath"),
    ("modelName", ""), ("toolCall", {"name": "run_command", "args": "{}"}),
    ("toolCall", {"name": "run_command", "args": {}, "id": "invented"}),
])
def test_unqualified_native_shape_refuses_before_http(policy, tmp_path, field, value):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, {**EVENT, field: value})
    assert result.returncode == 2
    assert fake.requests == []


def test_foreign_host_identity_refused(policy, tmp_path):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, extra={"ZENTINELLE_HARNESS": "claude"})
    assert result.returncode == 2
    assert fake.requests == []


def test_approval_hold_cannot_invent_missing_native_call_identity(policy, tmp_path):
    fake = policy({"decision": "ask", "allowed": False,
                   "approval": {"status": "pending", "request_id": EVENT["conversationId"],
                                "timeout_seconds": 10, "expires_at": "2099-01-01T00:00:00Z"}})
    result = run_hook(fake.url, tmp_path, extra={"ZENTINELLE_HARNESS": "antigravity"})
    assert result.returncode == 2
    assert len(fake.requests) == 1
    assert "tool_call_id" not in fake.requests[0][2]["context"]


def test_duplicate_json_refuses_before_http(policy, tmp_path):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, raw='{"conversationId":"a","conversationId":"b"}')
    assert result.returncode == 2
    assert fake.requests == []


def test_offline_refusal_ignores_legacy_fail_open(tmp_path):
    result = run_hook("http://127.0.0.1:1", tmp_path, extra={"ZENTINELLE_FAIL_OPEN": "1"})
    assert result.returncode == 2
    assert json.loads(result.stdout)["decision"] == "deny"


def test_required_configuration_cannot_release_hook(tmp_path):
    result = run_hook("", tmp_path, extra={"ZENTINELLE_KEY": ""})
    assert result.returncode == 2


def test_native_post_error_metadata_is_best_effort_audit(policy, tmp_path):
    fake = policy({})
    result = run_hook(fake.url, tmp_path, {**EVENT, "error": "native command failed"}, action="post")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}
    assert fake.requests[0][1] == "/api/zentinelle/v1/events"
    assert fake.requests[0][2]["events"][0]["payload"] == {
        "source": "antigravity_cli_hook", "tool": "run_command", "inputs": EVENT["toolCall"]["args"],
        "outputs": {"error": "native command failed"}, "session_id": EVENT["conversationId"], **METADATA,
    }


def test_post_offline_never_replays_or_claims_authorization(tmp_path):
    result = run_hook("http://127.0.0.1:1", tmp_path, {**EVENT, "error": ""}, action="post")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}
