#!/usr/bin/env python3
"""Best-effort bounded audit hook; never execution authorization."""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
from datetime import datetime, timezone

if __package__:
    from .transport import MAX_BYTES, NoRedirect, base_url, credential, read_event
else:
    from transport import MAX_BYTES, NoRedirect, base_url, credential, read_event

_TIMEOUT = 3
_NATIVE_SOURCES = {
    "PostToolUse": "claude_code_hook",
    "AfterTool": "gemini_cli_hook",
    "tool.execute.after": "opencode_plugin",
}


def _emit_async(endpoint, key, payload):
    request = urllib.request.Request(endpoint + "/api/zentinelle/v1/events", data=payload,
                                     headers={"Content-Type": "application/json", "X-Zentinelle-Key": key},
                                     method="POST")
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=_TIMEOUT):
            pass
    except Exception:
        pass  # Audit delivery never grants authority or replays a finished tool.


def main():
    try:
        env = dict(os.environ)
        endpoint, key = env.get("ZENTINELLE_ENDPOINT"), credential(env)
        if not endpoint or not key:
            return 0
        endpoint = base_url(endpoint)
        event = read_event(sys.stdin.buffer)
        if not isinstance(event, dict) or event.get("hook_event_name") not in _NATIVE_SOURCES:
            return 0
        details = {"tool": event.get("tool_name"), "inputs": event.get("tool_input"),
                   "outputs": event.get("tool_response"), "source": _NATIVE_SOURCES[event["hook_event_name"]]}
        for name in ("session_id", "tool_use_id", "tool_call_id", "chat_id", "turn_id"):
            if name in event:
                details[name] = event[name]
        body = {"events": [{"type": "tool_call", "category": "audit", "payload": details,
                           "timestamp": datetime.now(timezone.utc).isoformat(),
                           "user_id": env.get("ZENTINELLE_USER_ID", "")}]}
        if env.get("ZENTINELLE_AGENT_ID"):
            body["agent_id"] = env["ZENTINELLE_AGENT_ID"]
        payload = json.dumps(body, allow_nan=False).encode()
        if len(payload) > MAX_BYTES:
            return 0
        worker = threading.Thread(target=_emit_async, args=(endpoint, key, payload), daemon=True)
        worker.start()
        worker.join(timeout=_TIMEOUT + 0.5)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
