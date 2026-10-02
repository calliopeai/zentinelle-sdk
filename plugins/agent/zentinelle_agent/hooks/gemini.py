"""Install Gemini native hooks without persisting runtime credentials."""
from __future__ import annotations

from pathlib import Path

from .settings import command, script_path, update

find_hook_script = script_path
build_hook_command = command
_EVENTS = {"BeforeTool": "pre_tool", "AfterTool": "post_tool"}


def install_gemini_hooks(project_dir: str, endpoint: str, api_key: str, agent_id: str,
                         fail_open: bool = False) -> Path:
    commands = {name: command(script_path(name), endpoint, api_key, agent_id, fail_open) for name in _EVENTS.values()}
    return update(project_dir, ".gemini", _EVENTS, commands)


def uninstall_gemini_hooks(project_dir: str) -> Path:
    return update(project_dir, ".gemini", _EVENTS)
