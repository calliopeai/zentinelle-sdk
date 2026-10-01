"""Actual audit entrypoint/HTTP checks, never an authorization assertion."""

import json
import os
import subprocess
import sys
import time

import pytest
from test_policy_hardening import KEY, server
from test_pre_tool_agent_host import HOOK

AUDIT = HOOK.with_name("post_tool.py")


def audit(url, event=None, raw=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("ZENTINELLE_")}
    env.update(ZENTINELLE_ENDPOINT=url, ZENTINELLE_KEY=KEY, ZENTINELLE_USER_ID="fixture-user")
    return subprocess.run(
        [sys.executable, str(AUDIT)],
        env=env,
        input=raw if raw is not None else json.dumps(event),
        text=True,
        capture_output=True,
        timeout=10,
    )


@pytest.mark.parametrize("event_name,source", [("PostToolUse", "claude_code_hook"), ("AfterTool", "gemini_cli_hook")])
def test_native_audit_keeps_exact_inputs_outputs_and_source_identity(event_name, source):
    event = {
        "hook_event_name": event_name,
        "tool_name": "fixture-tool",
        "tool_input": {"command": "echo café"},
        "tool_response": {"result": ["done", False]},
        "session_id": "fixture-session",
        "tool_use_id": "fixture-call",
        "chat_id": "fixture-chat",
        "turn_id": "fixture-turn",
    }
    with server([(202, {})]) as (url, requests):
        result = audit(url, event)
    assert result.returncode == 0 and result.stdout + result.stderr == ""
    method, path, body, key = requests[0]
    assert method == "POST" and path == "/api/zentinelle/v1/events" and key == KEY
    assert "agent_id" not in body
    emitted = body["events"][0]
    assert emitted["user_id"] == "fixture-user"
    assert emitted["payload"] == {
        "tool": event["tool_name"],
        "inputs": event["tool_input"],
        "outputs": event["tool_response"],
        "source": source,
        "session_id": event["session_id"],
        "tool_use_id": event["tool_use_id"],
        "chat_id": event["chat_id"],
        "turn_id": event["turn_id"],
    }


def test_audit_redirect_does_not_forward_credentials_or_change_exit_status():
    with server([(200, {})]) as (target, received):
        with server([], redirect=target + "/stolen") as (url, requests):
            result = audit(url, {"hook_event_name": "AfterTool"})
    assert result.returncode == 0 and result.stdout + result.stderr == ""
    assert len(requests) == 1 and received == []


@pytest.mark.parametrize("raw", ["bad", '{"value":NaN}', '{"hook_event_name":"PreToolUse"}'])
def test_invalid_audit_input_never_posts_or_affects_execution(raw):
    with server([(200, {})]) as (url, requests):
        result = audit(url, raw=raw)
    assert result.returncode == 0 and requests == []


def test_offline_audit_is_best_effort():
    result = audit("http://127.0.0.1:1", {"hook_event_name": "PostToolUse"})
    assert result.returncode == 0 and result.stdout + result.stderr == ""


def test_slow_audit_response_cannot_hold_the_process_open():
    started = time.monotonic()
    with server([(200, {})], delays=[8]) as (url, requests):
        result = audit(url, {"hook_event_name": "AfterTool"})
    assert result.returncode == 0 and len(requests) == 1
    assert time.monotonic() - started < 4.5
