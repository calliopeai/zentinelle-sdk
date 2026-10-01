# zentinelle-agent

Owned Zentinelle hooks and a provider proxy for coding agents. These adapters use
native extension points; they do not modify or fork harness runtimes.

| Integration | Before execution | After execution |
|---|---|---|
| Claude Code settings | `PreToolUse` policy check | `PostToolUse` best-effort audit |
| Gemini CLI settings | `BeforeTool` policy check | `AfterTool` best-effort audit |
| Calliope CLI policy command | Exact `{id, name, arguments}` evaluation | Host-owned audit |
| Provider proxy | Evaluation of requests routed through the proxy | Service-managed provider handling |

Provider request governance does not authorize individual local tool effects.
For the native Codex plugin, use the separately maintained
[calliope-codex-tools](https://github.com/calliopeai/calliope-codex-tools) package.
Release and cross-harness qualification are tracked in
[rollout #400](https://github.com/calliopeai/calliope-cli/issues/400).

## Install and configure native hooks

Requires Python 3.9+ and a POSIX shell. Install the released package with
`pip install zentinelle-agent`; when testing unreleased source, use
`pip install ./plugins/agent` from this repository.

Supply a scoped agent credential through your environment or secret manager.
Keep this environment available when launching the harness:

```bash
export ZENTINELLE_ENDPOINT=https://your-zentinelle.example
# Set ZENTINELLE_KEY from your secret manager, without placing it in command history.
export ZENTINELLE_AGENT_ID=your-registered-agent
export ZENTINELLE_USER_ID=your-policy-subject
zentinelle-agent install          # Claude Code, current project
# Or:
zentinelle-agent install-gemini   # Gemini CLI, current project
```

Restart the harness to load the settings. `--project-dir` selects an existing
project. Claude's `--mode pre|post|both` defaults to both; post-only mode supplies
audit without a pre-execution policy check.

Settings contain the installed Python hook path and `ZENTINELLE_REQUIRED=1`.
Endpoint, key, agent ID, and user ID are inherited at execution, never stored in
settings. Legacy `--endpoint`, `--key`, and `--agent-id` arguments remain accepted
for install-time validation; they do not configure future harness processes.
Prefer environment variables so credentials do not appear in process arguments.
A required hook refuses execution when its runtime configuration is missing.
Harness environment filtering can remove credentials; validate credential delivery
in the target harness version before rollout. Do not disable organization security
settings to make an integration work.

Updates preserve unrelated settings and hooks, replace only handlers owned by this
package, and migrate legacy commands only when they invoke the exact installed
hook entrypoint. Invalid JSON, duplicate fields, symlinks, and an existing installer
lock are refused without replacing settings. Writes use a private temporary file
and atomic replacement; changes detected during installation are refused. Other
editors do not participate in the installer lock, so retry if concurrent changes
are reported. Repeating install or uninstall preserves unchanged file bytes.

```bash
zentinelle-agent status          # Inspect both harnesses without showing secrets
zentinelle-agent uninstall       # Remove owned Claude hooks
zentinelle-agent uninstall-gemini
zentinelle-agent install-skill   # Install the bundled Claude setup skill
```

Status confirms installed settings, not activation in a running harness.
Uninstall preserves unrelated settings and does not create an absent settings file.

## Policy checks and human oversight

Each configured pre-tool hook sends the original tool name, full input, and session
to `/api/zentinelle/v1/evaluate`; source call, chat, and turn IDs are preserved when
supplied. A missing session, malformed input, or conflicting invocation aliases is
refused. Calliope CLI's JSON format requires a call ID and
`ZENTINELLE_SESSION_ID`; the hook does not invent session identity.

Only a successful HTTP 200 response with an explicit, consistent
`{"decision":"allow","allowed":true}` releases the hook. An allow exits 0 with
no permission override, preserving ordinary harness confirmation. Denials use
the harness's native output shape and exit 2. Unknown decisions, inconsistent
fields, invalid JSON, and network errors refuse execution, even when the legacy
`ZENTINELLE_FAIL_OPEN=1` environment setting is present. Install-time `--fail-open`
is rejected. Language SDK clients retain their separate availability options.

Transport accepts HTTPS, with HTTP allowed only for literal loopback endpoints.
Redirects are refused without forwarding credentials. Input and response bodies
are limited to 1 MiB; input collection and each HTTP exchange have a total five
second deadline, including slow response bodies. Hook errors never echo remote
reason strings, approval tokens, or credentials.

Trusted agent-host callers can set `ZENTINELLE_HARNESS` and use
`ZENTINELLE_AGENT_HOST_KEY` instead of `ZENTINELLE_KEY`. Host credentials belong in
the trusted host process; do not inject them into unmodified third-party harnesses.
If both key variables are set, they must agree. See the backend's canonical
[agent-host contract](https://github.com/calliopeai/zentinelle/blob/main/docs/agent-host.md).

In host mode an `ask` holds the original invocation, requiring a canonical request
UUID, source call identity, and future expiry. The hook polls
`/api/zentinelle/v1/approvals/requests/<uuid>` and, after human approval, reevaluates
the same subject, session, and exact input with the returned token. The token alone
cannot authorize execution. Denial, expiry, malformed polling responses, changed
policy, or connection failure refuses the tool. The hold is capped at 300 seconds;
later polling responses cannot extend its original deadline. Non-host `ask`
responses refuse execution rather than inventing approval authority.

Post-tool audit preserves native source and invocation metadata, uses bounded
best-effort delivery, and always exits 0. It cannot authorize or replay a tool.

## Coverage limits

The SDK tests exercise actual hook subprocesses, HTTP exchanges, and settings files.
They do not prove native tool effects across every harness version or platform.
Native harness qualification and owned per-harness installers remain tracked in
the rollout issue. Windows settings installation is not supported by this POSIX
installer.

The harness controls hook loading and dispatch. Disabled, untrusted, skipped,
crashed, or externally terminated hooks can limit coverage. Hosted provider tools
that bypass local hook dispatch are outside this gate. Mandatory admission at
dispatch belongs in an owned host, including Calliope CLI, with coverage verified
against actual effects for each supported surface.

## Provider proxy

```bash
zentinelle-agent proxy --provider anthropic  # or openai, google
```

The proxy listens on `127.0.0.1:8742` by default and forwards requests to
Zentinelle's `/proxy/<provider>/` endpoint with `X-Zentinelle-Key`.
Provider API keys remain in provider authentication headers. Configure each
client's supported base-URL setting to route requests through the proxy; traffic
that does not use that endpoint is outside its coverage. `httpx>=0.24.0` supplies
proxy streaming. Native hook transport uses the Python standard library.

## Runtime environment

| Variable | Meaning |
|---|---|
| `ZENTINELLE_ENDPOINT` | Service base URL, optionally including a deployment prefix |
| `ZENTINELLE_KEY` | Scoped agent key, also used by the proxy |
| `ZENTINELLE_AGENT_ID` | Registered agent identity, when required |
| `ZENTINELLE_USER_ID` | Policy subject, verified by the service in host mode |
| `ZENTINELLE_SESSION_ID` | Calliope CLI policy-command session |
| `ZENTINELLE_HARNESS` | Trusted host harness slug; enables canonical oversight polling |
| `ZENTINELLE_AGENT_HOST_KEY` | Trusted host credential alias; keep it host-side |
| `ZENTINELLE_REQUIRED` | `1` makes absent configuration refuse execution |
| `ZENTINELLE_FAIL_OPEN` | Legacy value ignored by blocking hooks |
