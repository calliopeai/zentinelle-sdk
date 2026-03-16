"""
Write Zentinelle hooks into .claude/settings.json for a project.

Adds PreToolUse and PostToolUse hooks pointing at the installed hook scripts,
with Zentinelle env vars sourced from the caller's environment or explicit args.
Preserves any existing hooks configuration.
"""
import json
import os
import shutil
import sys
from pathlib import Path


def find_hook_script(name: str) -> str:
    """Return absolute path to an installed hook script."""
    # When installed as a package, scripts live next to this file
    here = Path(__file__).parent
    candidate = here / f"{name}.py"
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(f"Hook script not found: {candidate}")


def build_hook_command(
    script_path: str,
    endpoint: str,
    api_key: str,
    agent_id: str,
    fail_open: bool = False,
) -> str:
    """Build the shell command string Claude Code will invoke for a hook."""
    python = shutil.which("python3") or shutil.which("python") or sys.executable
    env_prefix = (
        f"ZENTINELLE_ENDPOINT={endpoint!r} "
        f"ZENTINELLE_KEY={api_key!r} "
        f"ZENTINELLE_AGENT_ID={agent_id!r} "
    )
    if fail_open:
        env_prefix += "ZENTINELLE_FAIL_OPEN=1 "
    return f"{env_prefix}{python} {script_path!r}"


def install_hooks(
    project_dir: str,
    endpoint: str,
    api_key: str,
    agent_id: str,
    fail_open: bool = False,
    mode: str = "both",  # "both" | "pre" | "post"
) -> Path:
    """
    Write Zentinelle hooks to .claude/settings.json in the given project directory.

    Returns the path to the settings file.
    """
    settings_path = Path(project_dir) / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing settings
    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            pass  # Overwrite corrupt settings

    if "hooks" not in settings:
        settings["hooks"] = {}

    pre_script = find_hook_script("pre_tool")
    post_script = find_hook_script("post_tool")

    pre_cmd = build_hook_command(pre_script, endpoint, api_key, agent_id, fail_open)
    post_cmd = build_hook_command(post_script, endpoint, api_key, agent_id)

    if mode in ("both", "pre"):
        # PreToolUse: runs before every tool call, can block with exit code 2
        pre_hooks = settings["hooks"].get("PreToolUse", [])
        # Remove any existing Zentinelle hook before re-adding
        pre_hooks = [h for h in pre_hooks if "zentinelle" not in json.dumps(h).lower()]
        pre_hooks.append({
            "matcher": "",  # Match all tools
            "hooks": [{"type": "command", "command": pre_cmd}],
        })
        settings["hooks"]["PreToolUse"] = pre_hooks

    if mode in ("both", "post"):
        # PostToolUse: runs after every tool call, fire-and-forget audit
        post_hooks = settings["hooks"].get("PostToolUse", [])
        post_hooks = [h for h in post_hooks if "zentinelle" not in json.dumps(h).lower()]
        post_hooks.append({
            "matcher": "",  # Match all tools
            "hooks": [{"type": "command", "command": post_cmd}],
        })
        settings["hooks"]["PostToolUse"] = post_hooks

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return settings_path


def uninstall_hooks(project_dir: str) -> Path:
    """Remove Zentinelle hooks from .claude/settings.json."""
    settings_path = Path(project_dir) / ".claude" / "settings.json"
    if not settings_path.exists():
        return settings_path

    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        return settings_path

    hooks = settings.get("hooks", {})
    for event in ("PreToolUse", "PostToolUse"):
        if event in hooks:
            hooks[event] = [
                h for h in hooks[event]
                if "zentinelle" not in json.dumps(h).lower()
            ]
            if not hooks[event]:
                del hooks[event]

    if not hooks:
        settings.pop("hooks", None)

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return settings_path
