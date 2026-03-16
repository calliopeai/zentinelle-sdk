#!/usr/bin/env python3
"""
Zentinelle PostToolUse hook for Claude Code.

Claude Code calls this script after every tool invocation. This is a
fire-and-forget audit emitter — it always exits 0, never blocks execution.

Environment variables:
  ZENTINELLE_ENDPOINT   Zentinelle base URL  (e.g. http://localhost:8000)
  ZENTINELLE_KEY        Agent API key
  ZENTINELLE_AGENT_ID   Agent identifier

Claude Code passes hook input as JSON on stdin:
  {
    "tool_name": "Bash",
    "tool_input": {"command": "ls"},
    "tool_response": {"output": "file.txt\n", "interrupted": false}
  }
"""
import json
import os
import sys
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone

_TIMEOUT = 3  # seconds


def _emit_async(endpoint: str, api_key: str, agent_id: str, payload: bytes) -> None:
    """Send audit event in a background thread — PostToolUse must not block."""
    req = urllib.request.Request(
        f"{endpoint}/api/zentinelle/v1/events",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Zentinelle-Key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT):
            pass
    except Exception:
        pass  # Fire and forget — never fail the hook


def main():
    endpoint = os.environ.get("ZENTINELLE_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("ZENTINELLE_KEY", "")
    agent_id = os.environ.get("ZENTINELLE_AGENT_ID", "")

    if not endpoint or not api_key:
        sys.exit(0)

    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        hook_input = {}

    tool_name = hook_input.get("tool_name", "unknown")
    tool_input = hook_input.get("tool_input", {})
    tool_response = hook_input.get("tool_response", {})

    payload = json.dumps({
        "agent_id": agent_id,
        "events": [
            {
                "type": "tool_call",
                "category": "audit",
                "payload": {
                    "tool": tool_name,
                    "inputs": tool_input,
                    "outputs": tool_response,
                    "source": "claude_code_hook",
                },
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "user_id": "",
            }
        ],
    }).encode()

    # Emit in background — PostToolUse exit code is ignored by Claude Code
    # but we still don't want to add latency
    t = threading.Thread(
        target=_emit_async,
        args=(endpoint, api_key, agent_id, payload),
        daemon=True,
    )
    t.start()
    t.join(timeout=_TIMEOUT + 0.5)  # Wait briefly so daemon thread completes before process exits

    sys.exit(0)


if __name__ == "__main__":
    main()
