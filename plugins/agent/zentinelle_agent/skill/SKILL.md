---
name: zentinelle
description: Set up Zentinelle AI governance for this coding agent session — hooks (tool-level policy enforcement + audit) and/or proxy (full API-level enforcement).
argument-hint: "[hooks|proxy|both|status|uninstall]"
disable-model-invocation: true
---

Set up Zentinelle governance for this coding agent session.

Mode: $ARGUMENTS (default: hooks)

## Steps

**1. Check installation**

Run this and check if it succeeds:
```bash
pip show zentinelle-agent
```

If not installed:
```bash
pip install zentinelle-agent
```

**2. Collect configuration**

Check the environment for existing config:
```bash
echo "ENDPOINT: ${ZENTINELLE_ENDPOINT:-not set}"
echo "KEY: ${ZENTINELLE_KEY:-not set}"
echo "AGENT_ID: ${ZENTINELLE_AGENT_ID:-not set}"
```

If any are missing, ask the user:
- **Endpoint**: URL of their Zentinelle instance (e.g. `http://localhost:8080` for local, or their hosted URL)
- **Key**: Agent API key (starts with `sk_agent_`)
- **Agent ID**: A label for this session (e.g. `claude-code-dev`, `codex-dev`, `gemini-dev`)

**3. Execute based on mode**

**`hooks`** (default — installs PreToolUse/PostToolUse hooks, Claude Code only):
```bash
zentinelle-agent install \
  --endpoint <endpoint> \
  --key <key> \
  --agent-id <agent-id>
```
Tell the user: hooks are active after restarting Claude Code.

**`proxy`** (full API-level enforcement — works with any agent):
Ask the user which provider they're using, then show these steps:

Step A — start the proxy (run in a separate terminal):
```bash
zentinelle-agent proxy \
  --endpoint <endpoint> \
  --key <key> \
  --provider <anthropic|openai|google>
```

Step B — point the agent at the proxy:
- **Claude Code**: `export ANTHROPIC_BASE_URL=http://127.0.0.1:8742`
- **Codex (OpenAI)**: `export OPENAI_BASE_URL=http://127.0.0.1:8742`
- **Gemini**: `export GOOGLE_API_BASE=http://127.0.0.1:8742`

**`both`** — do hooks first, then show proxy instructions.

**`status`** — show current installation state:
```bash
zentinelle-agent status
```

**`uninstall`** — remove hooks:
```bash
zentinelle-agent uninstall
```

**4. Confirm**

After setup, run `zentinelle-agent status` and show the user what's active.
Summarize in one sentence what enforcement is now in place.
