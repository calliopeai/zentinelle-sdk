"""The PreToolUse hook's agent host mode (zentinelle#377, calliope-vscode#794).

Runs the hook exactly as Claude Code does (a subprocess, hook input on stdin)
against a stand-in Zentinelle that speaks the agent host contract in
docs/agent-host.md of the zentinelle repo.
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "zentinelle_agent" / "hooks" / "pre_tool.py"
HOOK_INPUT = {
    "session_id": "a41f0c2e",
    "tool_use_id": "toolu_01",
    "tool_name": "Bash",
    "tool_input": {"command": "npm test"},
    "hook_event_name": "PreToolUse",
}


class FakeZentinelle:
    """Scripted /evaluate answers and approval request states, with a request log."""

    def __init__(self, decisions, approval_states=()):
        self.decisions = list(decisions)
        self.approval_states = list(approval_states)
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, body, status=200):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(("POST", self.path, body, self.headers.get("X-Zentinelle-Key")))
                self._reply(fake.decisions.pop(0))

            def do_GET(self):
                fake.requests.append(("GET", self.path, None, self.headers.get("X-Zentinelle-Key")))
                self._reply(fake.approval_states.pop(0))

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


def run_hook(url, extra_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ZENTINELLE_")}
    env.update({"ZENTINELLE_ENDPOINT": url, "ZENTINELLE_KEY": "sk_agent_host", "ZENTINELLE_HARNESS": "claude",
                "ZENTINELLE_USER_ID": "dev@example.com"})
    env.update(extra_env or {})
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(HOOK_INPUT), capture_output=True,
                          text=True, env=env, timeout=30)
    return proc.returncode, proc.stdout


@pytest.fixture
def zentinelle(request):
    fakes = []

    def make(decisions, approval_states=()):
        fake = FakeZentinelle(decisions, approval_states)
        fakes.append(fake)
        return fake

    yield make
    for fake in fakes:
        fake.close()


def test_allow_sends_the_host_context_and_exits_zero(zentinelle):
    fake = zentinelle([{"decision": "allow", "allowed": True}])
    code, _ = run_hook(fake.url)
    assert code == 0
    method, path, body, key = fake.requests[0]
    assert (method, path, key) == ("POST", "/api/zentinelle/v1/evaluate", "sk_agent_host")
    assert body == {
        "action": "tool_call",
        "user_id": "dev@example.com",
        "context": {"harness": "claude", "session_id": "a41f0c2e", "tool_call_id": "toolu_01",
                    "tool_name": "Bash", "tool_input": {"command": "npm test"}},
    }


def test_deny_blocks_with_the_reason(zentinelle):
    fake = zentinelle([{"decision": "deny", "allowed": False, "reason": "No shell"}])
    code, out = run_hook(fake.url)
    assert code == 2
    assert json.loads(out) == {"decision": "block", "reason": "No shell"}


def test_ask_holds_until_approved_then_retries_with_the_token(zentinelle):
    ask = {"decision": "ask", "allowed": False, "reason": "needs a human",
           "approval": {"request_id": "req-1", "status": "pending", "timeout_seconds": 30}}
    fake = zentinelle(
        [ask, {"decision": "allow", "allowed": True}],
        [{"request_id": "req-1", "status": "pending"},
         {"request_id": "req-1", "status": "approved", "approval_token": "tok-1"}],
    )
    code, _ = run_hook(fake.url)
    assert code == 0
    assert [(m, p) for m, p, _, _ in fake.requests] == [
        ("POST", "/api/zentinelle/v1/evaluate"),
        ("GET", "/api/zentinelle/v1/approvals/requests/req-1"),
        ("GET", "/api/zentinelle/v1/approvals/requests/req-1"),
        ("POST", "/api/zentinelle/v1/evaluate"),
    ]
    first, retry = fake.requests[0][2], fake.requests[3][2]
    assert "approval_token" not in first["context"]
    assert retry["context"] == {**first["context"], "approval_token": "tok-1"}


def test_ask_denied_by_a_person_blocks(zentinelle):
    ask = {"decision": "ask", "approval": {"request_id": "req-2", "timeout_seconds": 30}}
    fake = zentinelle([ask], [{"request_id": "req-2", "status": "denied", "reason": "Not on the release branch"}])
    code, out = run_hook(fake.url)
    assert code == 2
    assert json.loads(out)["reason"] == "Not on the release branch"


def test_a_retry_the_policy_now_refuses_blocks(zentinelle):
    ask = {"decision": "ask", "approval": {"request_id": "req-3", "timeout_seconds": 30}}
    fake = zentinelle([ask, {"decision": "deny", "reason": "policy changed"}],
                      [{"request_id": "req-3", "status": "approved", "approval_token": "t"}])
    code, out = run_hook(fake.url)
    assert code == 2
    assert json.loads(out)["reason"] == "policy changed"


def test_unreachable_zentinelle_fails_closed_unless_fail_open():
    code, out = run_hook("http://127.0.0.1:1")
    assert code == 2
    assert "Cannot reach Zentinelle" in json.loads(out)["reason"]
    code, _ = run_hook("http://127.0.0.1:1", {"ZENTINELLE_FAIL_OPEN": "1"})
    assert code == 0


def test_without_a_harness_the_legacy_request_is_unchanged(zentinelle):
    fake = zentinelle([{"allowed": True}])
    code, _ = run_hook(fake.url, {"ZENTINELLE_HARNESS": ""})
    assert code == 0
    body = fake.requests[0][2]
    assert body["context"]["source"] == "claude_code_hook"
    assert "harness" not in body["context"]
