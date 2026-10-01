"""Install Claude Code hooks, preserving settings and runtime-only secrets."""
from __future__ import annotations

from pathlib import Path

from .settings import command, script_path, update

find_hook_script = script_path
build_hook_command = command


def install_hooks(project_dir: str, endpoint: str, api_key: str, agent_id: str,
                  fail_open: bool = False, mode: str = "both") -> Path:
    if mode not in ("both", "pre", "post"):
        raise ValueError("Invalid hook installation mode")
    events = {}
    if mode in ("both", "pre"):
        events["PreToolUse"] = "pre_tool"
    if mode in ("both", "post"):
        events["PostToolUse"] = "post_tool"
    commands = {name: command(script_path(name), endpoint, api_key, agent_id, fail_open)
                for name in events.values()}
    return update(project_dir, ".claude", events, commands)


def uninstall_hooks(project_dir: str) -> Path:
    return update(project_dir, ".claude", {"PreToolUse": "pre_tool", "PostToolUse": "post_tool"})
