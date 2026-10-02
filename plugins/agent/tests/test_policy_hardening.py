"""Real one-shot hooks and HTTP transport; not native harness qualification."""

import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest
from test_pre_tool_agent_host import HOOK, HOOK_INPUT, future, hold

KEY = "sk_test_private_fixture_key"


@contextmanager
def server(replies, drip=False, redirect=None, delays=None):
    recorded = []
    stopping = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self):
            body = None
            if self.command == "POST":
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            recorded.append((self.command, self.path, body, self.headers.get("X-Zentinelle-Key")))
            if redirect:
                self.send_response(307)
                self.send_header("Location", redirect)
                self.end_headers()
                return
            status, value = replies.pop(0) if replies else (500, {})
            delay = delays.pop(0) if delays else 0
            if stopping.wait(delay):
                return
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                if drip:
                    for char in raw:
                        if stopping.is_set():
                            break
                        self.wfile.write(bytes([char]))
                        self.wfile.flush()
                        time.sleep(0.1)
                else:
                    self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        do_POST = respond
        do_GET = respond

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=lambda: http.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}", recorded
    finally:
        stopping.set()
        http.shutdown()
        http.server_close()
        worker.join()


def invoke(url="", event=HOOK_INPUT, env=None, raw=None):
    variables = {key: value for key, value in os.environ.items() if not key.startswith("ZENTINELLE_")}
    variables.update(
        ZENTINELLE_ENDPOINT=url, ZENTINELLE_KEY=KEY, ZENTINELLE_HARNESS="claude", ZENTINELLE_USER_ID="fixture-user"
    )
    variables.update(env or {})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw if raw is not None else json.dumps(event),
        text=True,
        capture_output=True,
        env=variables,
        timeout=10,
    )


@pytest.mark.parametrize(
    "response",
    [
        {},
        [],
        None,
        {"allowed": True},
        {"decision": "allow"},
        {"decision": "allow", "allowed": "true"},
        {"decision": "allow", "allowed": 1},
        {"decision": "allow", "allowed": False},
        {"decision": "ask", "allowed": True},
        {"decision": "unknown", "allowed": True},
        {"decision": "allow", "allowed": True, "context": []},
        {"decision": "allow", "allowed": True, "context": {"require_human_approval": True}},
        {"decision": "allow", "allowed": True, "context": {"session_id": "someone-else"}},
        {"decision": "allow", "allowed": True, "context": {"tool_input": {"command": "changed"}}},
        {"decision": "allow", "allowed": True, "subject": {"user_id": "someone-else"}},
        {"decision": "allow", "allowed": True, "contract_version": "999"},
        b'{"decision":"deny","decision":"allow","allowed":true}',
        b'{"decision":"allow","allowed":true,"extra":NaN}',
        b'{"decision":"allow","allowed":true,"extra":1e999}',
        b'{"decision":"allow","allowed":true,"extra":"' + b"x" * (1024 * 1024) + b'"}',
    ],
    ids=lambda value: type(value).__name__,
)
def test_only_explicit_consistent_valid_allow_releases_the_hook(response):
    with server([(200, response)]) as (url, requests):
        result = invoke(url)
    assert result.returncode == 2
    assert requests[0][2]["context"]["tool_input"] == HOOK_INPUT["tool_input"]


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_errors_never_release_or_echo_credentials_even_with_fail_open(status):
    with server([(status, {"reason": KEY})]) as (url, _requests):
        result = invoke(url, env={"ZENTINELLE_FAIL_OPEN": "1"})
    assert result.returncode == 2
    assert KEY not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "env",
    [
        {"ZENTINELLE_ENDPOINT": ""},
        {"ZENTINELLE_KEY": ""},
        {"ZENTINELLE_ENDPOINT": "", "ZENTINELLE_KEY": ""},
        {"ZENTINELLE_AGENT_HOST_KEY": "different"},
        {"ZENTINELLE_ENDPOINT": "http://example.invalid"},
    ],
)
def test_partial_host_configuration_or_unsafe_credentials_refuse_before_http(env):
    result = invoke(env=env)
    assert result.returncode == 2
    assert KEY not in result.stdout + result.stderr


def test_an_explicitly_required_hook_cannot_be_silent_when_unconfigured():
    result = invoke(
        env={"ZENTINELLE_ENDPOINT": "", "ZENTINELLE_KEY": "", "ZENTINELLE_HARNESS": "", "ZENTINELLE_REQUIRED": "1"}
    )
    assert result.returncode == 2


def test_skills_only_unconfigured_mode_remains_inactive():
    result = invoke(env={"ZENTINELLE_ENDPOINT": "", "ZENTINELLE_KEY": "", "ZENTINELLE_HARNESS": ""}, raw="bad")
    assert result.returncode == 0
    assert result.stdout == ""


def test_redirects_do_not_forward_a_credential_or_release_the_hook():
    with server([(200, {"decision": "allow", "allowed": True})]) as (target, received):
        with server([], redirect=target + "/stolen") as (url, requests):
            result = invoke(url)
    assert result.returncode == 2
    assert len(requests) == 1 and received == []


def test_dripping_bytes_cannot_extend_the_total_request_deadline():
    started = time.monotonic()
    with server([(200, {"decision": "allow", "allowed": True, "padding": "x" * 80})], drip=True) as (url, _requests):
        result = invoke(url)
    assert result.returncode == 2
    assert time.monotonic() - started < 6.5


@pytest.mark.parametrize("event_name", ["PreToolUse", "BeforeTool"])
def test_generic_claude_and_gemini_keep_exact_inputs_and_ordinary_confirmation(event_name):
    event = {
        **HOOK_INPUT,
        "hook_event_name": event_name,
        "tool_input": {"command": "echo café", "nested": [True, None, 1]},
    }
    with server([(200, {"decision": "allow", "allowed": True})]) as (url, requests):
        result = invoke(url, event=event, env={"ZENTINELLE_HARNESS": ""})
    assert result.returncode == 0 and result.stdout == ""
    assert requests[0][2]["context"]["tool_input"] == event["tool_input"]
    assert requests[0][2]["context"]["source"] == (
        "gemini_cli_hook" if event_name == "BeforeTool" else "claude_code_hook"
    )


def test_gemini_denial_uses_its_native_output_shape():
    with server([(200, {"decision": "deny", "allowed": False})]) as (url, _requests):
        result = invoke(url, event={**HOOK_INPUT, "hook_event_name": "BeforeTool"})
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"decision": "deny", "reason": "Blocked by Zentinelle policy"}


@pytest.mark.parametrize("change", ["request", "expires", "token", "token_expires", "status"])
def test_oversight_cannot_release_a_wrong_expired_or_malformed_approval(change):
    request_id = str(uuid4())
    status = {
        "request_id": request_id,
        "status": "approved",
        "expires_at": future(),
        "approval_token": "private-token",
        "approval_expires_at": future(),
    }
    if change == "request":
        status["request_id"] = str(uuid4())
    elif change == "expires":
        status["expires_at"] = future(-1)
    elif change == "token":
        status["approval_token"] = ""
    elif change == "token_expires":
        status["approval_expires_at"] = future(-1)
    else:
        status["status"] = "unknown"
    with server([(200, hold(request_id)), (200, status)]) as (url, requests):
        result = invoke(url)
    assert result.returncode == 2 and len(requests) == 2
    assert "private-token" not in result.stdout + result.stderr


def test_expiring_pending_hold_ends_without_an_execution_retry():
    request_id = str(uuid4())
    waiting = hold(request_id)
    waiting["approval"]["expires_at"] = future(1)
    with server([(200, waiting), (200, {"request_id": request_id, "status": "pending", "expires_at": future()})]) as (
        url,
        requests,
    ):
        result = invoke(url)
    assert result.returncode == 2
    assert [request[0] for request in requests] == ["POST", "GET"]


def test_approved_reevaluation_keeps_session_user_and_unicode_input():
    request_id = str(uuid4())
    status = {
        "request_id": request_id,
        "status": "approved",
        "expires_at": future(),
        "approval_token": "private-token",
        "approval_expires_at": future(),
    }
    event = {**HOOK_INPUT, "tool_input": {"command": "echo café", "flag": False}}
    with server([(200, hold(request_id)), (200, status), (200, {"decision": "allow", "allowed": True})]) as (
        url,
        requests,
    ):
        result = invoke(url, event=event)
    assert result.returncode == 0
    first, retry = requests[0][2], requests[2][2]
    assert retry == {**first, "context": {**first["context"], "approval_token": "private-token"}}
    assert all(request[3] == KEY for request in requests)


@pytest.mark.parametrize(
    "raw",
    [
        '{"session_id":"one","session_id":"two"}',
        '{"tool_input":{"value":1e999}}',
        '{"tool_input":{"value":Infinity}}',
        "[]",
        "not JSON",
        '"' + "x" * (1024 * 1024) + '"',
    ],
    ids=lambda value: "input-" + str(len(value)),
)
def test_invalid_or_oversized_event_is_refused_without_http(raw):
    with server([(200, {"decision": "allow", "allowed": True})]) as (url, requests):
        result = invoke(url, raw=raw)
    assert result.returncode == 2 and requests == []


@pytest.mark.parametrize(
    "event",
    [
        {**HOOK_INPUT, "session_id": ""},
        {**HOOK_INPUT, "tool_input": []},
        {**HOOK_INPUT, "tool_call_id": "another-call"},
        {"id": "one", "name": "Bash", "arguments": {"flag": True}, "tool_input": {"flag": 1}},
        {"id": "one", "name": "Bash", "arguments": {}, "tool_call_id": "two"},
        {"id": "one", "name": "Bash", "arguments": {}, "session_id": "other-session"},
    ],
)
def test_missing_identity_or_conflicting_aliases_are_refused_before_http(event):
    with server([(200, {"decision": "allow", "allowed": True})]) as (url, requests):
        result = invoke(url, event=event, env={"ZENTINELLE_SESSION_ID": HOOK_INPUT["session_id"]})
    assert result.returncode == 2 and requests == []


def test_approved_retry_cannot_outlive_its_token_deadline():
    request_id = str(uuid4())
    status = {
        "request_id": request_id,
        "status": "approved",
        "expires_at": future(),
        "approval_token": "private-token",
        "approval_expires_at": future(2),
    }
    with server(
        [(200, hold(request_id)), (200, status), (200, {"decision": "allow", "allowed": True})], delays=[0, 0, 3]
    ) as (url, requests):
        result = invoke(url)
    assert result.returncode == 2
    assert [request[0] for request in requests] == ["POST", "GET", "POST"]
    assert "private-token" not in result.stdout + result.stderr


def test_an_unfinished_stdin_pipe_exits_cleanly_at_the_input_deadline():
    variables = {key: value for key, value in os.environ.items() if not key.startswith("ZENTINELLE_")}
    variables.update(ZENTINELLE_REQUIRED="1", ZENTINELLE_ENDPOINT="http://127.0.0.1:1", ZENTINELLE_KEY=KEY)
    started = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, str(HOOK)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=variables,
    )
    try:
        process.stdin.write('{"session_id":')
        process.stdin.flush()
        process.wait(timeout=7)
        # Read only after termination; keep stdin open throughout the deadline.
        stdout, stderr = process.stdout.read(), process.stderr.read()
        assert process.returncode == 2
        assert time.monotonic() - started < 6.5
        assert "Tool input deadline exceeded" in stdout + stderr
        assert "Fatal Python error" not in stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()


def test_policy_subject_cannot_change_a_supplied_agent_identity():
    with server([(200, {"decision": "allow", "allowed": True, "subject": {"agent_id": "different-agent"}})]) as (
        url,
        requests,
    ):
        result = invoke(url, env={"ZENTINELLE_AGENT_ID": "fixture-agent"})
    assert result.returncode == 2 and requests[0][2]["agent_id"] == "fixture-agent"


@pytest.mark.parametrize("credential", [" ", "key with spaces", "key\nsecret"])
def test_invalid_credentials_are_refused_without_http_or_echo(credential):
    with server([(200, {"decision": "allow", "allowed": True})]) as (url, requests):
        result = invoke(url, env={"ZENTINELLE_KEY": credential})
    assert result.returncode == 2 and requests == []
    assert "key with spaces" not in result.stdout + result.stderr
