"""Real private settings files and installed hook subprocesses."""

import json
import os
import shlex
import stat
import subprocess
import sys

import pytest
from test_policy_hardening import KEY, server
from test_pre_tool_agent_host import HOOK_INPUT

from zentinelle_agent.hooks.gemini import install_gemini_hooks, uninstall_gemini_hooks
from zentinelle_agent.hooks.install import build_hook_command, install_hooks, uninstall_hooks
from zentinelle_agent.hooks.settings import script_path


@pytest.fixture(params=["claude", "gemini"])
def harness(request):
    if request.param == "claude":
        return ".claude", "PreToolUse", install_hooks, uninstall_hooks
    return ".gemini", "BeforeTool", install_gemini_hooks, uninstall_gemini_hooks


def seed(project, directory, value):
    folder = project / directory
    folder.mkdir()
    path = folder / "settings.json"
    path.write_text(json.dumps(value))
    return path


def test_real_install_update_uninstall_preserve_unrelated_settings_and_omit_secrets(tmp_path, harness):
    directory, event, install, uninstall = harness
    project = tmp_path / "project with 'quotes'"
    project.mkdir()
    other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo zentinelle unrelated"}]}
    original = {"model": "existing-user-model", "hooks": {event: [other]}, "custom": {"enabled": False}}
    path = seed(project, directory, original)
    install(str(project), "https://example.invalid", KEY, "fixture-agent")
    first = path.read_bytes()
    settings = json.loads(first)
    assert KEY.encode() not in first and b"https://example.invalid" not in first
    assert settings["model"] == original["model"] and settings["custom"] == original["custom"]
    assert settings["hooks"][event][0] == other
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    install(str(project), "https://example.invalid", KEY, "fixture-agent")
    assert path.read_bytes() == first
    uninstall(str(project))
    assert json.loads(path.read_bytes()) == original
    second = path.read_bytes()
    uninstall(str(project))
    assert path.read_bytes() == second
    assert not (path.parent / ".zentinelle-settings.lock").exists()


@pytest.mark.parametrize("raw", ["not JSON", "[]", '{"hooks": []}', '{"hooks":{},"hooks":{}}'])
def test_invalid_existing_settings_are_refused_without_overwrite(tmp_path, harness, raw):
    directory, _event, install, _uninstall = harness
    folder = tmp_path / directory
    folder.mkdir()
    path = folder / "settings.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        install(str(tmp_path), "https://example.invalid", KEY, "fixture-agent")
    assert path.read_text() == raw
    assert sorted(p.name for p in folder.iterdir()) == ["settings.json"]


def test_symlinked_settings_do_not_modify_the_target(tmp_path, harness):
    directory, _event, install, _uninstall = harness
    outside = tmp_path / "outside.json"
    outside.write_text('{"keep": true}')
    folder = tmp_path / directory
    folder.mkdir()
    (folder / "settings.json").symlink_to(outside)
    with pytest.raises(ValueError, match="Symlink"):
        install(str(tmp_path), "https://example.invalid", KEY, "fixture-agent")
    assert outside.read_text() == '{"keep": true}'


def test_only_owned_legacy_handler_is_migrated_and_scrubbed_from_a_mixed_group(tmp_path, harness):
    directory, event, install, _uninstall = harness
    legacy = {
        "type": "command",
        "command": "ZENTINELLE_KEY=" + KEY + " python3 " + shlex.quote(script_path("pre_tool")),
    }
    retained = {"type": "command", "command": "echo keep zentinelle"}
    original = {"hooks": {event: [{"matcher": "", "custom": True, "hooks": [legacy, retained]}]}}
    path = seed(tmp_path, directory, original)
    install(str(tmp_path), "https://example.invalid", KEY, "fixture-agent")
    settings = json.loads(path.read_bytes())
    assert KEY.encode() not in path.read_bytes()
    assert settings["hooks"][event][0] == {"matcher": "", "custom": True, "hooks": [retained]}


def test_an_existing_installer_lock_refuses_updates(tmp_path, harness):
    directory, _event, install, _uninstall = harness
    path = seed(tmp_path, directory, {"keep": "original"})
    lock = path.parent / ".zentinelle-settings.lock"
    lock.write_text("owned by another installer")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="locked"):
        install(str(tmp_path), "https://example.invalid", KEY, "fixture-agent")
    assert path.read_bytes() == original
    assert lock.read_text() == "owned by another installer"


def test_installed_command_uses_runtime_credentials_and_refuses_missing_configuration(tmp_path, harness):
    directory, event, install, _uninstall = harness
    native = {**HOOK_INPUT, "hook_event_name": event}
    with server([(200, {"decision": "allow", "allowed": True})]) as (url, requests):
        path = install(str(tmp_path), url, KEY, "fixture-agent")
        command = json.loads(path.read_bytes())["hooks"][event][0]["hooks"][0]["command"]
        env = {key: value for key, value in os.environ.items() if not key.startswith("ZENTINELLE_")}
        denied = subprocess.run(
            command, shell=True, env=env, input=json.dumps(native), text=True, capture_output=True, timeout=10
        )
        assert denied.returncode == 2 and requests == []
        env.update(ZENTINELLE_KEY=KEY, ZENTINELLE_ENDPOINT=url)
        allowed = subprocess.run(
            command, shell=True, env=env, input=json.dumps(native), text=True, capture_output=True, timeout=10
        )
    assert allowed.returncode == 0 and allowed.stdout == ""
    assert requests[0][3] == KEY
    assert requests[0][2]["context"]["tool_input"] == native["tool_input"]


def test_legacy_fail_open_install_option_is_rejected():
    with pytest.raises(ValueError, match="Fail-open"):
        build_hook_command(script_path("pre_tool"), "https://example.invalid", KEY, "fixture-agent", True)


def test_uninstall_without_an_install_does_not_create_settings(tmp_path, harness):
    directory, _event, _install, uninstall = harness
    assert uninstall(str(tmp_path)) == tmp_path / directory / "settings.json"
    assert not (tmp_path / directory).exists()


def cli(project, command, env=None, extra=()):
    variables = {key: value for key, value in os.environ.items() if not key.startswith("ZENTINELLE_")}
    home = project / "private-home"
    home.mkdir(exist_ok=True)
    variables["HOME"] = str(home)
    variables.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "zentinelle_agent.cli", command, "--project-dir", str(project), *extra],
        env=variables,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_cli_lifecycle_reports_both_harnesses_without_exposing_configuration(tmp_path):
    env = {"ZENTINELLE_KEY": KEY, "ZENTINELLE_ENDPOINT": "https://example.invalid"}
    for command in ("install", "install-gemini"):
        result = cli(tmp_path, command, env)
        assert result.returncode == 0, result.stderr
        assert "runtime environment" in result.stdout
        assert KEY not in result.stdout + result.stderr
        assert env["ZENTINELLE_ENDPOINT"] not in result.stdout + result.stderr
    status = cli(tmp_path, "status")
    assert status.returncode == 0
    assert "PreToolUse: runtime environment" in status.stdout
    assert "BeforeTool: runtime environment" in status.stdout
    assert "PostToolUse: runtime environment" in status.stdout
    assert "AfterTool: runtime environment" in status.stdout
    for command in ("uninstall", "uninstall-gemini"):
        assert cli(tmp_path, command).returncode == 0
    assert cli(tmp_path, "status").stdout.count("not installed") == 2


def test_status_ignores_unrelated_handlers_and_does_not_echo_legacy_credentials(tmp_path):
    handler = {"type": "command", "command": "echo zentinelle unrelated"}
    path = seed(tmp_path, ".claude", {"hooks": {"PreToolUse": [{"hooks": [handler]}]}})
    assert "Claude Code: Zentinelle hooks not installed" in cli(tmp_path, "status").stdout
    legacy = {
        "type": "command",
        "command": "ZENTINELLE_KEY=" + KEY + " python3 " + shlex.quote(script_path("pre_tool")),
    }
    path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [legacy]}]}}))
    status = cli(tmp_path, "status")
    assert status.returncode == 0
    assert "legacy command; reinstall to migrate" in status.stdout
    assert KEY not in status.stdout + status.stderr


def test_cli_invalid_config_and_fail_open_have_clean_errors_without_mutation(tmp_path):
    path = seed(tmp_path, ".claude", {"keep": True})
    original = path.read_bytes()
    env = {"ZENTINELLE_KEY": KEY, "ZENTINELLE_ENDPOINT": "https://example.invalid"}
    rejected = cli(tmp_path, "install", env, ["--fail-open"])
    assert rejected.returncode == 1 and "Fail-open" in rejected.stderr
    assert "Traceback" not in rejected.stderr and path.read_bytes() == original
    path.write_text('{"hooks":[]}')
    status = cli(tmp_path, "status")
    assert status.returncode == 1 and "Traceback" not in status.stderr
    assert path.read_text() == '{"hooks":[]}'


def test_empty_unrelated_hook_groups_survive_install_and_uninstall(tmp_path, harness):
    directory, event, install, uninstall = harness
    original = {"hooks": {event: [{"matcher": "never", "hooks": [], "custom": True}]}}
    path = seed(tmp_path, directory, original)
    install(str(tmp_path), "https://example.invalid", KEY, "fixture-agent")
    uninstall(str(tmp_path))
    assert json.loads(path.read_bytes()) == original


def test_bundled_skill_installs_to_private_home_and_preserves_claude_invocation_fields(tmp_path):
    result = cli(tmp_path, "install-skill")
    assert result.returncode == 0, result.stderr
    installed = tmp_path / "private-home" / ".claude" / "skills" / "zentinelle" / "SKILL.md"
    text = installed.read_text()
    assert "disable-model-invocation: true" in text
    assert "argument-hint:" in text
    assert "never print key values" in text
    assert "ZENTINELLE_AGENT_HOST_KEY=" not in text
