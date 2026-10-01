#!/usr/bin/env python3
"""Strict coding-agent pre-tool hook with bounded agent-host oversight.

Only explicit valid allow releases a configured hook. ZENTINELLE_FAIL_OPEN
never bypasses this gate; language-SDK availability settings remain separate.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from uuid import UUID

if __package__:
    from .transport import PolicyError, base_url, credential, decision, expiry, read_event, request_json
else:
    from transport import PolicyError, base_url, credential, decision, expiry, read_event, request_json

_EVALUATE = "/api/zentinelle/v1/evaluate"
_POLL_SECONDS = 2
_MAX_HOLD_SECONDS = 300
_NATIVE_SOURCES = {
    "PreToolUse": "claude_code_hook",
    "BeforeTool": "gemini_cli_hook",
    "tool.execute.before": "opencode_plugin",
    "preToolUse": "copilot_cli_hook",
}


def _identity(value, name, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise PolicyError("Missing or invalid " + name)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PolicyError("Invalid " + name)
    return value


def invocation(event, env):
    if not isinstance(event, dict):
        raise PolicyError("Invalid pre-tool event")
    cli = "name" in event or "arguments" in event or "id" in event
    if cli:
        for left, right in (("name", "tool_name"), ("arguments", "tool_input"),
                            ("id", "tool_use_id"), ("id", "tool_call_id")):
            if left in event and right in event:
                if json.dumps(event[left], sort_keys=True) != json.dumps(event[right], sort_keys=True):
                    raise PolicyError("Conflicting tool invocation fields")
        tool, args = event.get("name"), event.get("arguments")
        call_id = _identity(event.get("id"), "tool call identity")
        session = env.get("ZENTINELLE_SESSION_ID")
        if "session_id" in event and event["session_id"] != session:
            raise PolicyError("Conflicting session identity")
    else:
        if event.get("hook_event_name") not in _NATIVE_SOURCES:
            raise PolicyError("Invalid pre-tool event")
        tool, args = event.get("tool_name"), event.get("tool_input")
        call_id = _identity(event.get("tool_use_id", event.get("tool_call_id")), "tool call identity",
                            event.get("hook_event_name") == "tool.execute.before")
        if "tool_use_id" in event and "tool_call_id" in event and event["tool_use_id"] != event["tool_call_id"]:
            raise PolicyError("Conflicting tool call identity")
        session = event.get("session_id")
    tool = _identity(tool, "tool name")
    session = _identity(session, "session identity")
    if not isinstance(args, dict):
        raise PolicyError("Missing exact tool input")
    context = {"session_id": session, "tool_name": tool, "tool_input": args}
    if call_id:
        context["tool_call_id"] = call_id
    for name in ("chat_id", "turn_id", "cwd", "model", "permission_mode", "timestamp"):
        if name in event:
            context[name] = event[name]
    harness = env.get("ZENTINELLE_HARNESS", "")
    if event.get("hook_event_name") == "tool.execute.before" and harness and harness != "opencode":
        raise PolicyError("Conflicting native harness identity")
    if event.get("hook_event_name") == "preToolUse" and harness and harness != "copilot":
        raise PolicyError("Conflicting native harness identity")
    if harness:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,49}", harness):
            raise PolicyError("Invalid harness identity")
        context["harness"] = harness
    else:
        source = _NATIVE_SOURCES.get(event.get("hook_event_name"), "claude_code_hook")
        context.update(tool=tool, source="calliope_cli_policy" if cli else source)
    body = {"action": "tool_call", "context": context}
    for source, target in (("ZENTINELLE_AGENT_ID", "agent_id"), ("ZENTINELLE_USER_ID", "user_id")):
        if env.get(source):
            body[target] = _identity(env[source], target)
    return body


def _hold(endpoint, key, body, result):
    approval = result.get("approval")
    if not isinstance(approval, dict) or approval.get("status") != "pending":
        raise PolicyError("Invalid approval hold")
    if not body["context"].get("tool_call_id"):
        raise PolicyError("Approval hold requires a source tool call identity")
    request_id = approval.get("request_id")
    try:
        if str(UUID(request_id)) != request_id:
            raise ValueError()
    except Exception:
        raise PolicyError("Invalid approval request identity") from None
    timeout = approval.get("timeout_seconds")
    if type(timeout) is not int or timeout <= 0:
        raise PolicyError("Invalid approval timeout")
    deadline = min(expiry(approval.get("expires_at")), time.monotonic() + min(timeout, _MAX_HOLD_SECONDS))
    path = "/api/zentinelle/v1/approvals/requests/" + request_id
    while time.monotonic() < deadline:
        status = request_json(endpoint, key, path, deadline=deadline)
        if status.get("request_id") != request_id:
            raise PolicyError("Approval request identity changed")
        deadline = min(deadline, expiry(status.get("expires_at")))
        state = status.get("status")
        if state == "approved":
            token = status.get("approval_token")
            if not isinstance(token, str) or not token.strip() or len(token) > 8192:
                raise PolicyError("Invalid approval token")
            deadline = min(deadline, expiry(status.get("approval_expires_at")))
            # The original invocation is preserved. A token alone cannot
            # release it: current server policy must allow this exact retry.
            retry = {**body, "context": {**body["context"], "approval_token": token}}
            final = request_json(endpoint, key, _EVALUATE, retry, deadline)
            if decision(final, retry) != "allow":
                raise PolicyError("Policy refused the approved invocation")
            if time.monotonic() >= deadline:
                raise PolicyError("Approval deadline elapsed before release")
            return
        if state != "pending":
            raise PolicyError("Approval was denied, expired or invalid")
        time.sleep(min(_POLL_SECONDS, max(0, deadline - time.monotonic())))
    raise PolicyError("Approval deadline elapsed before release")


def evaluate(event, env):
    endpoint, key = env.get("ZENTINELLE_ENDPOINT", ""), credential(env)
    required = env.get("ZENTINELLE_REQUIRED") == "1" or env.get("ZENTINELLE_HARNESS")
    if not endpoint and not key and not required:
        return
    if not endpoint or not key:
        raise PolicyError("Incomplete Zentinelle configuration")
    endpoint = base_url(endpoint)
    body = invocation(event, env)
    result = request_json(endpoint, key, _EVALUATE, body)
    selected = decision(result, body)
    if selected == "ask" and env.get("ZENTINELLE_HARNESS"):
        _hold(endpoint, key, body, result)
    elif selected != "allow":
        raise PolicyError("Blocked by Zentinelle policy")


def main():
    event = {}
    try:
        env = dict(os.environ)
        required = env.get("ZENTINELLE_REQUIRED") == "1" or env.get("ZENTINELLE_HARNESS")
        if not env.get("ZENTINELLE_ENDPOINT") and not credential(env) and not required:
            return 0
        event = read_event(sys.stdin.buffer)
        evaluate(event, env)
        return 0
    except Exception as error:
        reason = str(error) if isinstance(error, PolicyError) else "Invalid policy check; tool refused"
        if isinstance(event, dict) and event.get("hook_event_name") == "BeforeTool":
            output = {"decision": "deny", "reason": reason}
        else:
            output = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}
        print(json.dumps(output))
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
