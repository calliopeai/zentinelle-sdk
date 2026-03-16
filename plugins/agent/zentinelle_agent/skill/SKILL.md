---
name: zentinelle
description: Set up Zentinelle AI governance for this Claude Code session — hooks (tool-level policy enforcement + audit) and/or proxy (full API-level enforcement).
argument-hint: "[hooks|proxy|both|status|uninstall]"
disable-model-invocation: true
---

Set up Zentinelle governance for this Claude Code session.

Mode: $ARGUMENTS (default: hooks)

## Steps

**1. Check installation**

Run this and check if it succeeds:
```bash
pip show zentinelle-claude-code
```

If not installed:
```bash
pip install zentinelle-claude-code
```

**2. Collect configuration**

Check the environment for existing config:
```bash
echo "ENDPOINT: ${ZENTINELLE_ENDPOINT:-not set}"
echo "KEY: ${ZENTINELLE_KEY:-not set}"
echo "AGENT_ID: ${ZENTINELLE_AGENT_ID:-not set}"
```

If any are missing, ask the user:
- **Endpoint**: URL of their Zentinelle instance (e.g. `http://localhost:8000` for local, or their hosted URL)
- **Key**: Agent API key (starts with `sk_agent_`, `znt_`, or `sk_test_`)
- **Agent ID**: A label for this session (default: `claude-code`, can be anything descriptive)

**3. Execute based on mode**

**`hooks`** (default — installs PreToolUse/PostToolUse hooks):
```bash
zentinelle-claude-code install \
  --endpoint <endpoint> \
  --key <key> \
  --agent-id <agent-id>
```
Tell the user: hooks are active after restarting Claude Code.

**`proxy`** (full API-level enforcement):
Show the user these two steps:

Step A — start the proxy (run in a separate terminal):
```bash
ZENTINELLE_ENDPOINT=<endpoint> ZENTINELLE_KEY=<key> \
  zentinelle-claude-code proxy
```

Step B — point Claude Code at it (in the terminal where they launch `claude`):
```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8742
```

**`both`** — do hooks first, then show proxy instructions.

**`status`** — show current installation state:
```bash
zentinelle-claude-code status
```

**`uninstall`** — remove hooks:
```bash
zentinelle-claude-code uninstall
```

**4. Confirm**

After setup, run `zentinelle-claude-code status` and show the user what's active.
Summarize in one sentence what enforcement is now in place.
