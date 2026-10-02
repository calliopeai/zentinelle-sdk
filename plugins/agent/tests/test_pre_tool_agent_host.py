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
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

HOOK = Path(__file__).resolve().parents[1] / "zentinelle_agent" / "hooks" / "pre_tool.py"
HOOK_INPUT = {
    "session_id": "a41f0c2e",
    "tool_use_id": "toolu_01",
    "tool_name": "Bash",
    "tool_input": {"command": "npm test"},
    "hook_event_name": "PreToolUse",
}


REQ1, REQ2, REQ3 = str(uuid4()), str(uuid4()), str(uuid4())


def future(seconds=30):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def hold(request_id=REQ1, seconds=30):
    return {
        "decision": "ask",
        "allowed": False,
        "approval": {
            "request_id": request_id,
            "status": "pending",
            "timeout_seconds": seconds,
            "expires_at": future(seconds),
        },
    }


def denial_reason(out):
    result = json.loads(out)
    return result.get("reason") or result["hookSpecificOutput"]["permissionDecisionReason"]


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


def run_hook(url, extra_env=None, hook_input=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ZENTINELLE_")}
    env.update(
        {
            "ZENTINELLE_ENDPOINT": url,
            "ZENTINELLE_KEY": "sk_agent_host",
            "ZENTINELLE_HARNESS": "claude",
            "ZENTINELLE_USER_ID": "dev@example.com",
        }
    )
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(hook_input or HOOK_INPUT),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
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
        "context": {
            "harness": "claude",
            "session_id": "a41f0c2e",
            "tool_call_id": "toolu_01",
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
        },
    }


def test_deny_blocks_without_echoing_untrusted_server_text(zentinelle):
    fake = zentinelle([{"decision": "deny", "allowed": False, "reason": "No shell"}])
    code, out = run_hook(fake.url)
    assert code == 2
    assert denial_reason(out) == "Blocked by Zentinelle policy"


def test_ask_holds_until_approved_then_retries_with_the_token(zentinelle):
    ask = {
        "decision": "ask",
        "allowed": False,
        "reason": "needs a human",
        "approval": {"request_id": REQ1, "status": "pending", "timeout_seconds": 30, "expires_at": future()},
    }
    fake = zentinelle(
        [ask, {"decision": "allow", "allowed": True}],
        [
            {"request_id": REQ1, "status": "pending", "expires_at": future()},
            {
                "request_id": REQ1,
                "status": "approved",
                "approval_token": "tok-1",
                "expires_at": future(),
                "approval_expires_at": future(),
            },
        ],
    )
    code, _ = run_hook(fake.url)
    assert code == 0
    assert [(m, p) for m, p, _, _ in fake.requests] == [
        ("POST", "/api/zentinelle/v1/evaluate"),
        ("GET", "/api/zentinelle/v1/approvals/requests/" + REQ1),
        ("GET", "/api/zentinelle/v1/approvals/requests/" + REQ1),
        ("POST", "/api/zentinelle/v1/evaluate"),
    ]
    first, retry = fake.requests[0][2], fake.requests[3][2]
    assert "approval_token" not in first["context"]
    assert retry["context"] == {**first["context"], "approval_token": "tok-1"}


def test_ask_denied_by_a_person_blocks(zentinelle):
    ask = hold(REQ2)
    fake = zentinelle(
        [ask], [{"request_id": REQ2, "status": "denied", "reason": "Not on the release branch", "expires_at": future()}]
    )
    code, out = run_hook(fake.url)
    assert code == 2
    assert denial_reason(out) == "Approval was denied, expired or invalid"


def test_a_retry_the_policy_now_refuses_blocks(zentinelle):
    ask = hold(REQ3)
    fake = zentinelle(
        [ask, {"decision": "deny", "allowed": False, "reason": "policy changed"}],
        [
            {
                "request_id": REQ3,
                "status": "approved",
                "approval_token": "t",
                "expires_at": future(),
                "approval_expires_at": future(),
            }
        ],
    )
    code, out = run_hook(fake.url)
    assert code == 2
    assert denial_reason(out) == "Policy refused the approved invocation"


def test_unreachable_zentinelle_fails_closed_even_with_legacy_fail_open():
    code, out = run_hook("http://127.0.0.1:1")
    assert code == 2
    assert "Policy service unavailable" in denial_reason(out)
    code, _ = run_hook("http://127.0.0.1:1", {"ZENTINELLE_FAIL_OPEN": "1"})
    assert code == 2


def test_generic_request_preserves_tool_source_and_invocation_identity(zentinelle):
    fake = zentinelle([{"decision": "allow", "allowed": True}])
    code, _ = run_hook(fake.url, {"ZENTINELLE_HARNESS": ""})
    assert code == 0
    body = fake.requests[0][2]
    assert body["context"]["source"] == "claude_code_hook"
    assert "harness" not in body["context"]


def test_calliope_cli_policy_command_shape_is_accepted(zentinelle):
    fake = zentinelle([{"decision": "deny", "allowed": False, "reason": "no"}])
    code, _ = run_hook(
        fake.url,
        {"ZENTINELLE_HARNESS": "calliope", "ZENTINELLE_SESSION_ID": "cli-1"},
        {"id": "call_9", "name": "bash", "arguments": {"command": "ls"}},
    )
    assert code == 2
    assert fake.requests[0][2]["context"] == {
        "harness": "calliope",
        "session_id": "cli-1",
        "tool_call_id": "call_9",
        "tool_name": "bash",
        "tool_input": {"command": "ls"},
    }
