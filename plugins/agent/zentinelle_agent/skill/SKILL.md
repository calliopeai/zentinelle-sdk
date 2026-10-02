---
name: zentinelle
description: Install or inspect Zentinelle native policy hooks and audit for Claude Code or Gemini CLI, or configure the optional provider proxy. Use for setup, status, and uninstall requests.
argument-hint: "[hooks|proxy|both|status|uninstall]"
disable-model-invocation: true
---

Configure the requested integration using `zentinelle-agent`. Default mode is hooks.
Check `zentinelle-agent --help`; install the released package with
`pip install zentinelle-agent` if needed, honoring the user's environment choice.

For hooks, determine whether the target is Claude Code or Gemini CLI and which
project to configure. Check only whether `ZENTINELLE_ENDPOINT` and
`ZENTINELLE_KEY` are present; never print key values, request credentials in chat,
or place them in settings, commands, or committed files. If missing, have the user
configure a scoped agent key through their environment or secret manager.
Agent and user identity, when required by policy, also come from the environment
of the process that launches the harness. Host credentials remain in a trusted
host, not a third-party harness.

| Request | Claude Code | Gemini CLI |
|---|---|---|
| Install or update hooks | `zentinelle-agent install` | `zentinelle-agent install-gemini` |
| Inspect both harness settings | `zentinelle-agent status` | Same command |
| Remove owned hooks | `zentinelle-agent uninstall` | `zentinelle-agent uninstall-gemini` |

Use `--project-dir` for another existing project. Install preserves unrelated
settings and refuses invalid settings; repair only changes the user authorizes.
Runtime configuration is inherited, so install-time flags do not configure future
harness sessions. Restart the target harness to load its hooks, then inspect
status. State that status confirms settings, not hook activation or effect coverage.
Do not enable fail-open: blocking hooks require an explicit valid service allow.

For requested proxy mode, use `zentinelle-agent proxy --provider` with `anthropic`,
`openai`, or `google`, inheriting endpoint and key from the environment. Run the
proxy in the user-selected persistent process environment, and configure the
client's supported base URL to its loopback listener. Provider request governance
does not authorize local tool effects. For `both`, configure native hooks and the
proxy separately.

Report the installed path and the selected integration. Native harnesses own
hook dispatch, so disabled or skipped hooks and hosted tools that bypass local
dispatch are outside this coverage. Mandatory dispatch admission requires an
owned host. Do not modify or fork third-party harness runtimes.
