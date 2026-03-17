"""
Write Zentinelle hooks into .gemini/settings.json for a project.

Adds pre-tool and post-tool hooks for Gemini CLI.
"""
import json
import os
import shutil
import sys
from pathlib import Path


def find_hook_script(name: str) -> str:
    """Return absolute path to an installed hook script."""
    # Re-use the existing Claude hook scripts (they use the same Zentinelle API)
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
    """Build the shell command string Gemini CLI will invoke for a hook."""
    python = shutil.which("python3") or shutil.which("python") or sys.executable
    env_prefix = (
        f"ZENTINELLE_ENDPOINT={endpoint!r} "
        f"ZENTINELLE_KEY={api_key!r} "
        f"ZENTINELLE_AGENT_ID={agent_id!r} "
    )
    if fail_open:
        env_prefix += "ZENTINELLE_FAIL_OPEN=1 "
    return f"{env_prefix}{python} {script_path!r}"


def install_gemini_hooks(
    project_dir: str,
    endpoint: str,
    api_key: str,
    agent_id: str,
    fail_open: bool = False,
) -> Path:
    """
    Write Zentinelle hooks to .gemini/settings.json in the given project directory.
    """
    settings_path = Path(project_dir) / ".gemini" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing settings
    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            pass

    if "hooks" not in settings:
        settings["hooks"] = {}

    pre_script = find_hook_script("pre_tool")
    post_script = find_hook_script("post_tool")

    pre_cmd = build_hook_command(pre_script, endpoint, api_key, agent_id, fail_open)
    post_cmd = build_hook_command(post_script, endpoint, api_key, agent_id)

    if not isinstance(settings["hooks"], dict):
        settings["hooks"] = {}

    # Event keys: BeforeTool, AfterTool
    # Each value: array of { matcher: "", hooks: [ { type: "command", command: "..." } ] }
    for event, cmd in (("BeforeTool", pre_cmd), ("AfterTool", post_cmd)):
        event_hooks = settings["hooks"].get(event, [])
        if not isinstance(event_hooks, list):
            event_hooks = []
        
        # Remove any existing Zentinelle hooks for this event
        event_hooks = [h for h in event_hooks if "zentinelle" not in json.dumps(h).lower()]
        
        event_hooks.append({
            "matcher": "",
            "hooks": [{"type": "command", "command": cmd}]
        })
        settings["hooks"][event] = event_hooks

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return settings_path


def uninstall_gemini_hooks(project_dir: str) -> Path:
    """Remove Zentinelle hooks from .gemini/settings.json."""
    settings_path = Path(project_dir) / ".gemini" / "settings.json"
    if not settings_path.exists():
        return settings_path

    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        return settings_path

    if "hooks" in settings:
        if isinstance(settings["hooks"], dict):
            for event in list(settings["hooks"].keys()):
                event_hooks = settings["hooks"][event]
                if isinstance(event_hooks, list):
                    settings["hooks"][event] = [
                        h for h in event_hooks
                        if "zentinelle" not in json.dumps(h).lower()
                    ]
                if not settings["hooks"][event]:
                    del settings["hooks"][event]
        else:
            settings["hooks"] = [
                h for h in settings["hooks"]
                if "zentinelle" not in json.dumps(h).lower()
            ]
        if not settings["hooks"]:
            del settings["hooks"]

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return settings_path
