#!/usr/bin/env python3
"""Observed native Antigravity CLI callbacks; preserve conversation and step identity."""
from __future__ import annotations

import json
import os
import sys
from uuid import UUID

if __package__:
    from .post_tool import emit
    from .pre_tool import evaluate, invocation
    from .transport import PolicyError, read_event
else:
    from post_tool import emit
    from pre_tool import evaluate, invocation
    from transport import PolicyError, read_event

METADATA = ("conversationId", "stepIdx", "workspacePaths", "transcriptPath", "artifactDirectoryPath", "modelName")


def text_field(value, limit=4096, absolute=False):
    if not isinstance(value, str) or not value or len(value) > limit:
        raise PolicyError("Missing or invalid native Antigravity field")
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or (absolute and not value.startswith("/")):
        raise PolicyError("Invalid native Antigravity field")
    return value


def normalize(event, action):
    if not isinstance(event, dict) or action not in ("pre", "post"):
        raise PolicyError("Invalid native Antigravity event")
    if any(name in event for name in ("hook_event_name", "tool_name", "tool_input", "session_id", "tool_call_id",
                                     "tool_use_id", "name", "arguments", "id", "source", "harness")):
        raise PolicyError("Conflicting native Antigravity fields")
    conversation = text_field(event.get("conversationId"), 255)
    try:
        if str(UUID(conversation)) != conversation:
            raise ValueError()
    except ValueError:
        raise PolicyError("Invalid native Antigravity conversation identity") from None
    step = event.get("stepIdx")
    if type(step) is not int or step < 0:
        raise PolicyError("Invalid native Antigravity trajectory step")
    workspaces = event.get("workspacePaths")
    if not isinstance(workspaces, list) or not workspaces or len(workspaces) > 32:
        raise PolicyError("Invalid native Antigravity workspaces")
    for workspace in workspaces:
        text_field(workspace, absolute=True)
    for name in ("transcriptPath", "artifactDirectoryPath"):
        text_field(event.get(name), absolute=True)
    text_field(event.get("modelName"), 255)
    tool = event.get("toolCall")
    if not isinstance(tool, dict) or set(tool) != {"name", "args"}:
        raise PolicyError("Missing or conflicting native Antigravity tool call")
    normalized = {
        "hook_event_name": "antigravity.PreToolUse" if action == "pre" else "antigravity.PostToolUse",
        "session_id": conversation,
        "tool_name": tool["name"],
        "tool_input": tool["args"],
        **{name: event[name] for name in METADATA},
    }
    # Internal namespaced callback labels distinguish this payload from Claude.
    # The central session identifier is the actually emitted conversation UUID.
    invocation({**normalized, "hook_event_name": "antigravity.PreToolUse"}, {})
    if action == "post":
        error = event.get("error")
        if "error" in event and (not isinstance(error, str) or len(error) > 65536):
            raise PolicyError("Invalid native Antigravity result metadata")
        normalized["tool_response"] = {"error": error} if "error" in event else {}
    return normalized


def main(action="pre"):
    try:
        env = dict(os.environ)
        event = normalize(read_event(sys.stdin.buffer), action)
        if action == "post":
            emit(event, env)
            print("{}")
            return 0
        evaluate(event, env)
        # "allow" would grant native permission. Ask continues existing native
        # approval/Always Allow behavior after the policy gate has released.
        print(json.dumps({"decision": "ask"}))
        return 0
    except Exception as error:
        if action == "post":
            print("{}")
            return 0
        reason = str(error) if isinstance(error, PolicyError) else "Invalid policy check; tool refused"
        print(json.dumps({"decision": "deny", "reason": reason}))
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) == 2 else "pre"))
