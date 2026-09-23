#!/usr/bin/env python3
"""
Zentinelle PreToolUse hook for Claude Code.

Claude Code calls this script before every tool invocation. If this script
exits with code 2 and writes JSON to stdout, Claude Code will block the tool
call and show the reason to the user.

Exit codes:
  0  — allow (or Zentinelle unreachable and ZENTINELLE_FAIL_OPEN=1)
  2  — block ({"decision": "block", "reason": "..."} written to stdout)

Environment variables:
  ZENTINELLE_ENDPOINT   Zentinelle base URL  (e.g. http://localhost:8000)
  ZENTINELLE_KEY        Agent API key        (sk_agent_... or znt_...)
  ZENTINELLE_AGENT_ID   Agent identifier
  ZENTINELLE_FAIL_OPEN  Set to "1" to allow tool calls when Zentinelle is
                        unreachable (default: block when unreachable)
  ZENTINELLE_HARNESS    Set inside an agent host (calliope-vscode#790): the
                        key is the host's agent_host key and this names the
                        harness (claude, codex, calliope). The call then
                        follows the agent host contract (zentinelle#377):
                        host context, and an "ask" is held until a person
                        approves or denies it (docs/agent-host.md).
  ZENTINELLE_USER_ID    The person driving the session (approvals bind to it)

Claude Code passes hook input as JSON on stdin:
  {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}, ...}
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

_TIMEOUT = 5  # seconds — keep latency low; this is in the hot path
_POLL_SECONDS = 2


def _block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(2)


def _allow() -> None:
    sys.exit(0)


def main():
    endpoint = os.environ.get("ZENTINELLE_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("ZENTINELLE_KEY", "")
    agent_id = os.environ.get("ZENTINELLE_AGENT_ID", "")
    fail_open = os.environ.get("ZENTINELLE_FAIL_OPEN", "0") == "1"

    if not endpoint or not api_key:
        # Not configured — pass through silently
        _allow()

    # Read hook input from Claude Code
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        hook_input = {}

    tool_name = hook_input.get("tool_name", "unknown")
    tool_input = hook_input.get("tool_input", {})

    harness = os.environ.get("ZENTINELLE_HARNESS", "")
    if harness:
        # calliope-cli's policy.command sends {id, name, arguments}; same
        # meaning, so one hook serves both harnesses.
        if "tool_name" not in hook_input and "name" in hook_input:
            hook_input = {"tool_name": hook_input.get("name"), "tool_input": hook_input.get("arguments", {}),
                          "tool_use_id": hook_input.get("id"), "session_id": os.environ.get("ZENTINELLE_SESSION_ID")}
        _agent_host(endpoint, api_key, harness, hook_input, fail_open)

    # Call Zentinelle evaluate endpoint
    payload = json.dumps({
        "agent_id": agent_id,
        "action": "tool_call",
        "context": {
            "tool": tool_name,
            "tool_input": tool_input,
            "source": "claude_code_hook",
        },
    }).encode()

    req = urllib.request.Request(
        f"{endpoint}/api/zentinelle/v1/evaluate",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Zentinelle-Key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if fail_open:
            _allow()
        _block(f"Zentinelle policy check failed (HTTP {e.code}): {body[:200]}")
    except (urllib.error.URLError, OSError, TimeoutError):
        if fail_open:
            _allow()
        _block(
            "Cannot reach Zentinelle policy server. "
            "Set ZENTINELLE_FAIL_OPEN=1 to allow tool calls when Zentinelle is offline."
        )
    except json.JSONDecodeError:
        if fail_open:
            _allow()
        _block("Invalid response from Zentinelle policy server.")

    if not result.get("allowed", True):
        reason = result.get("reason") or "Blocked by Zentinelle policy"
        policies = result.get("policies_evaluated", [])
        if policies:
            reason += f" (policies: {', '.join(policies)})"
        _block(reason)

    _allow()


def _post(endpoint, api_key, path, body):
    req = urllib.request.Request(
        f"{endpoint}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Zentinelle-Key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read())


def _get(endpoint, api_key, path):
    req = urllib.request.Request(f"{endpoint}{path}", headers={"X-Zentinelle-Key": api_key})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read())


def _agent_host(endpoint, api_key, harness, hook_input, fail_open):
    """The agent host contract (zentinelle#377): allow, deny, or hold on ask.

    Every exit path ends the process: allow exits 0, anything else blocks.
    """
    body = {
        "action": "tool_call",
        "context": {
            "harness": harness,
            "session_id": hook_input.get("session_id") or "unknown",
            "tool_name": hook_input.get("tool_name", "unknown"),
            "tool_input": hook_input.get("tool_input", {}),
        },
    }
    if hook_input.get("tool_use_id"):
        body["context"]["tool_call_id"] = hook_input["tool_use_id"]
    user_id = os.environ.get("ZENTINELLE_USER_ID", "")
    if user_id:
        body["user_id"] = user_id

    try:
        result = _post(endpoint, api_key, "/api/zentinelle/v1/evaluate", body)
        decision = result.get("decision")
        if decision == "ask":
            approval = result.get("approval") or {}
            request_id = approval.get("request_id")
            timeout = min(int(approval.get("timeout_seconds") or 300), 300)
            if not request_id:
                _block(result.get("reason") or "Approval required")
            deadline = time.monotonic() + timeout
            while True:
                status = _get(endpoint, api_key, f"/api/zentinelle/v1/approvals/requests/{request_id}")
                if status.get("status") == "approved":
                    body["context"]["approval_token"] = status["approval_token"]
                    result = _post(endpoint, api_key, "/api/zentinelle/v1/evaluate", body)
                    decision = result.get("decision")
                    break
                if status.get("status") != "pending":
                    _block(status.get("reason") or f"Approval {status.get('status')}")
                if time.monotonic() >= deadline:
                    _block("No approval arrived in time")
                time.sleep(_POLL_SECONDS)
    except urllib.error.HTTPError as e:
        if fail_open:
            _allow()
        _block(f"Zentinelle policy check failed (HTTP {e.code}): {e.read().decode(errors='replace')[:200]}")
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, KeyError):
        if fail_open:
            _allow()
        _block("Cannot reach Zentinelle policy server.")

    if decision == "allow":
        _allow()
    _block(result.get("reason") or "Blocked by Zentinelle policy")


if __name__ == "__main__":
    main()
