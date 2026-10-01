"""Private, atomic, ownership-specific updates for native harness settings."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

from .transport import MAX_BYTES, PolicyError, base_url, credential, parse_json

_NAMES = {"pre_tool": "zentinelle-policy-v1", "post_tool": "zentinelle-audit-v1"}


def script_path(name):
    path = Path(__file__).parent / (name + ".py")
    if not path.is_file():
        raise ValueError("Installed hook script is missing")
    return str(path.resolve())


def command(script_path, endpoint, api_key, agent_id, fail_open=False):
    if os.name != "posix":
        raise ValueError("This settings installer requires a POSIX shell")
    if fail_open:
        raise ValueError("Fail-open is unsupported for blocking hooks")
    try:
        base_url(endpoint)
        if not credential({"ZENTINELLE_KEY": api_key}):
            raise PolicyError("Missing credential")
    except PolicyError:
        raise ValueError("Valid runtime Zentinelle endpoint and credential are required") from None
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("Agent identity is required")
    python = shutil.which("python3") or sys.executable
    # Secrets and identities come from the launching process, never settings.
    return "ZENTINELLE_REQUIRED=1 " + shlex.quote(python) + " " + shlex.quote(script_path)


def owned_handler(handler, name):
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return False
    if handler.get("name") == _NAMES[name]:
        return True
    try:
        tokens = shlex.split(handler.get("command", ""))
        # Migrate only old invocations of this exact installed entrypoint,
        # not unrelated handlers whose text mentions "zentinelle".
        while tokens and re.fullmatch(r"ZENTINELLE_[A-Z_]+=.*", tokens[0], flags=re.DOTALL):
            tokens.pop(0)
        return len(tokens) == 2 and bool(re.fullmatch(r"python(?:[0-9.]+)?", Path(tokens[0]).name)) \
            and str(Path(tokens[1]).resolve()) == script_path(name)
    except (ValueError, TypeError, OSError):
        return False


def _read(path):
    if path.is_symlink():
        raise ValueError("Symlinked harness settings are refused")
    if not path.exists():
        return None, {}
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("Harness settings exceed the limit")
    try:
        settings = parse_json(raw)
        if not isinstance(settings, dict):
            raise PolicyError("Settings must be an object")
    except PolicyError:
        raise ValueError("Invalid harness settings; original file preserved") from None
    return raw, settings


def update(project_dir, directory, events, commands=None):
    project = Path(project_dir).resolve()
    if not project.is_dir():
        raise ValueError("Project directory is unavailable")
    folder = project / directory
    if folder.is_symlink():
        raise ValueError("Symlinked harness directory is refused")
    path = folder / "settings.json"
    if commands is None and not folder.exists():
        return path
    folder.mkdir(mode=0o700, exist_ok=True)
    lock = folder / ".zentinelle-settings.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("Harness settings are locked by another installer") from None
    os.close(fd)
    temporary = None
    try:
        original, settings = _read(path)
        if commands is None and original is None:
            return path
        hooks = settings.get("hooks", {})
        if not isinstance(hooks, dict):
            raise ValueError("Invalid hooks settings; original file preserved")
        for event, name in events.items():
            groups = hooks.get(event, [])
            if not isinstance(groups, list):
                raise ValueError("Invalid hook event settings; original file preserved")
            kept = []
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    raise ValueError("Invalid hook group; original file preserved")
                handlers = [handler for handler in group["hooks"] if not owned_handler(handler, name)]
                if handlers or not group["hooks"]:
                    kept.append({**group, "hooks": handlers})
            if commands is not None:
                handler = {"name": _NAMES[name], "type": "command", "command": commands[name],
                           "timeout": (315000 if directory == ".gemini" else 315) if name == "pre_tool"
                           else (5000 if directory == ".gemini" else 5)}
                kept.append({"matcher": "*", "hooks": [handler]})
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event, None)
        if hooks:
            settings["hooks"] = hooks
        else:
            settings.pop("hooks", None)
        if settings == (parse_json(original) if original is not None else {}) and original is not None:
            return path
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(settings, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Native tools/editors do not share our lock. Detect a concurrent write
        # before replacing a file, rather than silently dropping their change.
        latest, _unused = _read(path)
        if latest != original:
            raise ValueError("Harness settings changed during installation; retry")
        os.replace(temporary, path)
        temporary = None
        return path
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def installed_hooks(project_dir, directory, events):
    """Read owned handlers only, without exposing stored legacy credentials."""
    folder = Path(project_dir) / directory
    if folder.is_symlink():
        raise ValueError("Symlinked harness directory is refused")
    path = folder / "settings.json"
    _raw, settings = _read(path)
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Invalid hooks settings")
    found = []
    for event, name in events.items():
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError("Invalid hook event settings")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError("Invalid hook group")
            for handler in group["hooks"]:
                if owned_handler(handler, name):
                    found.append((event, handler.get("name") == _NAMES[name]))
    return path, found
