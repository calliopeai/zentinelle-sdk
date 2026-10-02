#!/usr/bin/env python3
"""Native Copilot CLI camelCase command hooks; no fabricated call identity."""
from __future__ import annotations

import json
import os
import sys

if __package__:
    from .post_tool import emit
    from .pre_tool import evaluate, invocation
    from .transport import PolicyError, read_event
else:
    from post_tool import emit
    from pre_tool import evaluate, invocation
    from transport import PolicyError, read_event


def normalize(event, action):
    if not isinstance(event, dict) or action not in ("pre", "post"):
        raise PolicyError("Invalid Copilot hook event")
    if any(name in event for name in ("hook_event_name", "tool_name", "tool_input", "session_id",
                                     "tool_call_id", "tool_use_id", "name", "arguments", "id")):
        raise PolicyError("Conflicting native Copilot fields")
    timestamp = event.get("timestamp")
    cwd = event.get("cwd")
    if type(timestamp) is not int or timestamp < 0:
        raise PolicyError("Invalid native Copilot timestamp")
    if not isinstance(cwd, str) or not cwd or len(cwd) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in cwd):
        raise PolicyError("Invalid native Copilot working directory")
    normalized = {
        "hook_event_name": "preToolUse" if action == "pre" else "postToolUse",
        "session_id": event.get("sessionId"),
        "tool_name": event.get("toolName"),
        "tool_input": event.get("toolArgs"),
        "timestamp": timestamp,
        "cwd": cwd,
    }
    # Reuse canonical validation for exact native session, tool and object input.
    invocation({**normalized, "hook_event_name": "preToolUse"}, {})
    if action == "post":
        result = event.get("toolResult")
        if not isinstance(result, dict):
            raise PolicyError("Missing native Copilot tool result")
        normalized["tool_response"] = result
    return normalized


def main(action="pre"):
    try:
        env = dict(os.environ)
        event = normalize(read_event(sys.stdin.buffer), action)
        if action == "post":
            return emit(event, env)
        evaluate(event, env)
        print(json.dumps({"permissionDecision": "allow"}))
        return 0
    except Exception as error:
        if action == "post":
            return 0
        reason = str(error) if isinstance(error, PolicyError) else "Invalid policy check; tool refused"
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) == 2 else "pre"))
