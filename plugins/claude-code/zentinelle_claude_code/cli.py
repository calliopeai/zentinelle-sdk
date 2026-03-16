"""
zentinelle-claude-code CLI

Commands:
  install   Write Zentinelle hooks to .claude/settings.json
  uninstall Remove Zentinelle hooks from .claude/settings.json
  proxy     Start local header-injecting proxy server
  status    Show current installation state

Usage:
  zentinelle-claude-code install \\
    --endpoint http://localhost:8000 \\
    --key sk_agent_... \\
    --agent-id my-claude-session

  zentinelle-claude-code proxy \\
    --endpoint http://localhost:8000 \\
    --key sk_agent_...

  ZENTINELLE_ENDPOINT=http://localhost:8000 \\
  ZENTINELLE_KEY=sk_agent_... \\
  zentinelle-claude-code install
"""
import argparse
import json
import os
import sys
from pathlib import Path


def _require(name: str, value: str | None, env_var: str) -> str:
    if value:
        return value
    v = os.environ.get(env_var, "")
    if v:
        return v
    print(f"Error: --{name} is required (or set {env_var})", file=sys.stderr)
    sys.exit(1)


def cmd_install(args):
    from zentinelle_claude_code.hooks.install import install_hooks

    endpoint = _require("endpoint", args.endpoint, "ZENTINELLE_ENDPOINT")
    key = _require("key", args.key, "ZENTINELLE_KEY")
    agent_id = args.agent_id or os.environ.get("ZENTINELLE_AGENT_ID", "claude-code")
    project_dir = args.project_dir or os.getcwd()

    settings_path = install_hooks(
        project_dir=project_dir,
        endpoint=endpoint,
        api_key=key,
        agent_id=agent_id,
        fail_open=args.fail_open,
        mode=args.mode,
    )

    print(f"Zentinelle hooks installed: {settings_path}")
    print()
    print(f"  Endpoint : {endpoint}")
    print(f"  Agent ID : {agent_id}")
    print(f"  Mode     : {args.mode}")
    print(f"  Fail open: {args.fail_open}")
    print()
    print("Restart Claude Code to activate hooks.")


def cmd_uninstall(args):
    from zentinelle_claude_code.hooks.install import uninstall_hooks

    project_dir = args.project_dir or os.getcwd()
    settings_path = uninstall_hooks(project_dir=project_dir)
    print(f"Zentinelle hooks removed from: {settings_path}")


def cmd_proxy(args):
    from zentinelle_claude_code.proxy import run_proxy

    endpoint = _require("endpoint", args.endpoint, "ZENTINELLE_ENDPOINT")
    key = _require("key", args.key, "ZENTINELLE_KEY")
    port = args.port
    host = args.host

    run_proxy(
        zentinelle_endpoint=endpoint,
        zentinelle_key=key,
        port=port,
        host=host,
    )


def cmd_status(args):
    project_dir = args.project_dir or os.getcwd()
    settings_path = Path(project_dir) / ".claude" / "settings.json"

    if not settings_path.exists():
        print("No .claude/settings.json found.")
        return

    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        print(f"Cannot parse {settings_path}")
        return

    hooks = settings.get("hooks", {})
    zentinelle_hooks = {}

    for event in ("PreToolUse", "PostToolUse"):
        event_hooks = hooks.get(event, [])
        znt = [h for h in event_hooks if "zentinelle" in json.dumps(h).lower()]
        if znt:
            zentinelle_hooks[event] = znt

    if not zentinelle_hooks:
        print("Zentinelle hooks: not installed")
        return

    print(f"Zentinelle hooks installed in: {settings_path}")
    for event, event_hooks in zentinelle_hooks.items():
        for hook in event_hooks:
            for h in hook.get("hooks", []):
                cmd = h.get("command", "")
                # Extract endpoint from command for display
                import re
                m = re.search(r"ZENTINELLE_ENDPOINT='?([^' ]+)'?", cmd)
                endpoint = m.group(1) if m else "(unknown)"
                m2 = re.search(r"ZENTINELLE_AGENT_ID='?([^' ]+)'?", cmd)
                agent_id = m2.group(1) if m2 else "(unknown)"
                print(f"  {event}: endpoint={endpoint} agent_id={agent_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zentinelle-claude-code",
        description="Zentinelle governance for Claude Code sessions",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # install
    p_install = sub.add_parser("install", help="Install Zentinelle hooks into .claude/settings.json")
    p_install.add_argument("--endpoint", help="Zentinelle base URL (or ZENTINELLE_ENDPOINT)")
    p_install.add_argument("--key", help="Zentinelle agent API key (or ZENTINELLE_KEY)")
    p_install.add_argument("--agent-id", dest="agent_id", help="Agent identifier (default: claude-code)")
    p_install.add_argument("--project-dir", dest="project_dir", help="Project root (default: cwd)")
    p_install.add_argument("--fail-open", dest="fail_open", action="store_true",
                           help="Allow tool calls when Zentinelle is unreachable")
    p_install.add_argument("--mode", choices=("both", "pre", "post"), default="both",
                           help="Which hooks to install (default: both)")
    p_install.set_defaults(func=cmd_install)

    # uninstall
    p_uninstall = sub.add_parser("uninstall", help="Remove Zentinelle hooks")
    p_uninstall.add_argument("--project-dir", dest="project_dir", help="Project root (default: cwd)")
    p_uninstall.set_defaults(func=cmd_uninstall)

    # proxy
    p_proxy = sub.add_parser("proxy", help="Start local proxy (for full API-level enforcement)")
    p_proxy.add_argument("--endpoint", help="Zentinelle base URL (or ZENTINELLE_ENDPOINT)")
    p_proxy.add_argument("--key", help="Zentinelle agent API key (or ZENTINELLE_KEY)")
    p_proxy.add_argument("--port", type=int, default=8742, help="Local proxy port (default: 8742)")
    p_proxy.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p_proxy.set_defaults(func=cmd_proxy)

    # status
    p_status = sub.add_parser("status", help="Show Zentinelle hook installation state")
    p_status.add_argument("--project-dir", dest="project_dir", help="Project root (default: cwd)")
    p_status.set_defaults(func=cmd_status)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
