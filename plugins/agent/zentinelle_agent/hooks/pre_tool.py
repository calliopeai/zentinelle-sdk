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

Claude Code passes hook input as JSON on stdin:
  {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}, ...}
"""
import json
import os
import sys
import urllib.request
import urllib.error

_TIMEOUT = 5  # seconds — keep latency low; this is in the hot path


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


if __name__ == "__main__":
    main()
