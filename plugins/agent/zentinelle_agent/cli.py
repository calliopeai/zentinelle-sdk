"""
zentinelle-agent CLI

Commands:
  install        Write Zentinelle hooks to .claude/settings.json
  uninstall      Remove Zentinelle hooks from .claude/settings.json
  proxy          Start local header-injecting proxy server
  status         Show current installation state
  install-skill  Install /zentinelle slash command into Claude Code

Usage:
  zentinelle-agent install \\
    --endpoint http://localhost:8000 \\
    --key sk_agent_... \\
    --agent-id my-agent

  zentinelle-agent proxy \\
    --endpoint http://localhost:8000 \\
    --key sk_agent_... \\
    --provider openai

  zentinelle-agent install-skill

  ZENTINELLE_ENDPOINT=http://localhost:8000 \\
  ZENTINELLE_KEY=sk_agent_... \\
  zentinelle-agent install
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
    from zentinelle_agent.hooks.install import install_hooks

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


def cmd_install_gemini(args):
    from zentinelle_agent.hooks.gemini import install_gemini_hooks

    endpoint = _require("endpoint", args.endpoint, "ZENTINELLE_ENDPOINT")
    key = _require("key", args.key, "ZENTINELLE_KEY")
    agent_id = args.agent_id or os.environ.get("ZENTINELLE_AGENT_ID", "gemini-cli")
    project_dir = args.project_dir or os.getcwd()

    settings_path = install_gemini_hooks(
        project_dir=project_dir,
        endpoint=endpoint,
        api_key=key,
        agent_id=agent_id,
        fail_open=args.fail_open,
    )

    print(f"Zentinelle Gemini hooks installed: {settings_path}")
    print()
    print(f"  Endpoint : {endpoint}")
    print(f"  Agent ID : {agent_id}")
    print(f"  Fail open: {args.fail_open}")
    print()
    print("Gemini CLI hooks are active for this project.")


def cmd_uninstall(args):
    from zentinelle_agent.hooks.install import uninstall_hooks

    project_dir = args.project_dir or os.getcwd()
    settings_path = uninstall_hooks(project_dir=project_dir)
    print(f"Zentinelle hooks removed from: {settings_path}")


def cmd_uninstall_gemini(args):
    from zentinelle_agent.hooks.gemini import uninstall_gemini_hooks

    project_dir = args.project_dir or os.getcwd()
    settings_path = uninstall_gemini_hooks(project_dir=project_dir)
    print(f"Zentinelle Gemini hooks removed from: {settings_path}")


def cmd_proxy(args):
    from zentinelle_agent.proxy import run_proxy

    endpoint = _require("endpoint", args.endpoint, "ZENTINELLE_ENDPOINT")
    key = _require("key", args.key, "ZENTINELLE_KEY")
    port = args.port
    host = args.host

    run_proxy(
        zentinelle_endpoint=endpoint,
        zentinelle_key=key,
        provider=args.provider,
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


def cmd_install_skill(args):
    import shutil
    from pathlib import Path

    # Skill source: bundled with this package
    here = Path(__file__).parent
    skill_src = here / "skill" / "SKILL.md"
    if not skill_src.exists():
        print(f"Error: skill file not found at {skill_src}", file=sys.stderr)
        sys.exit(1)

    # Destination: user-level skill (available in every project)
    # or project-level (current directory only)
    if args.project:
        dest_dir = Path(args.project_dir or os.getcwd()) / ".claude" / "skills" / "zentinelle"
        scope = "project"
    else:
        dest_dir = Path.home() / ".claude" / "skills" / "zentinelle"
        scope = "user"

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / "SKILL.md"
    shutil.copy2(skill_src, dest_file)

    print(f"Zentinelle skill installed ({scope}-level): {dest_file}")
    print()
    print("In Claude Code, type:")
    print("  /zentinelle          — guided setup (hooks mode)")
    print("  /zentinelle proxy    — set up proxy mode")
    print("  /zentinelle both     — hooks + proxy")
    print("  /zentinelle status   — show current state")
    print("  /zentinelle uninstall")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zentinelle-agent",
        description="Zentinelle governance for AI coding agents",
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

    # install-gemini
    p_install_gemini = sub.add_parser("install-gemini", help="Install Zentinelle hooks into .gemini/settings.json")
    p_install_gemini.add_argument("--endpoint", help="Zentinelle base URL (or ZENTINELLE_ENDPOINT)")
    p_install_gemini.add_argument("--key", help="Zentinelle agent API key (or ZENTINELLE_KEY)")
    p_install_gemini.add_argument("--agent-id", dest="agent_id", help="Agent identifier (default: gemini-cli)")
    p_install_gemini.add_argument("--project-dir", dest="project_dir", help="Project root (default: cwd)")
    p_install_gemini.add_argument("--fail-open", dest="fail_open", action="store_true",
                                  help="Allow tool calls when Zentinelle is unreachable")
    p_install_gemini.set_defaults(func=cmd_install_gemini)

    # uninstall-gemini
    p_uninstall_gemini = sub.add_parser("uninstall-gemini", help="Remove Zentinelle Gemini hooks")
    p_uninstall_gemini.add_argument("--project-dir", dest="project_dir", help="Project root (default: cwd)")
    p_uninstall_gemini.set_defaults(func=cmd_uninstall_gemini)

    # proxy
    p_proxy = sub.add_parser("proxy", help="Start local proxy (for full API-level enforcement)")
    p_proxy.add_argument("--endpoint", help="Zentinelle base URL (or ZENTINELLE_ENDPOINT)")
    p_proxy.add_argument("--key", help="Zentinelle agent API key (or ZENTINELLE_KEY)")
    p_proxy.add_argument(
        "--provider",
        choices=("anthropic", "openai", "google"),
        default="anthropic",
        help="Provider proxy target (default: anthropic)",
    )
    p_proxy.add_argument("--port", type=int, default=8742, help="Local proxy port (default: 8742)")
    p_proxy.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p_proxy.set_defaults(func=cmd_proxy)

    # status
    p_status = sub.add_parser("status", help="Show Zentinelle hook installation state")
    p_status.add_argument("--project-dir", dest="project_dir", help="Project root (default: cwd)")
    p_status.set_defaults(func=cmd_status)

    # install-skill
    p_skill = sub.add_parser(
        "install-skill",
        help="Install /zentinelle slash command into Claude Code (~/.claude/skills/)",
    )
    p_skill.add_argument(
        "--project", action="store_true",
        help="Install into .claude/skills/ of current project instead of ~/.claude/skills/",
    )
    p_skill.add_argument("--project-dir", dest="project_dir", help="Project root (default: cwd)")
    p_skill.set_defaults(func=cmd_install_skill)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
