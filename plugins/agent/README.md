# zentinelle-agent

Zentinelle governance integration for AI coding agents — Claude Code, Codex, Gemini, and any OpenAI/Anthropic/Google-compatible agent.

Two complementary modes — use one or both:

| Mode | What it does | Works with |
|------|-------------|------------|
| **Hooks** | Intercepts every tool call via PreToolUse/PostToolUse hooks | Claude Code |
| **Proxy** | Routes all LLM API calls through Zentinelle for policy enforcement | Any agent (Claude Code, Codex, Gemini, custom) |

---

## Installation

```bash
pip install zentinelle-agent
```

---

## Quick start by agent

### Claude Code

```bash
# Option A: Hooks (tool-level enforcement)
zentinelle-agent install \
  --endpoint http://localhost:8080 \
  --key sk_agent_your_key \
  --agent-id claude-code-dev

# Option B: Proxy (API-level enforcement)
zentinelle-agent proxy --endpoint http://localhost:8080 --key sk_agent_your_key --provider anthropic
# Then in another terminal:
export ANTHROPIC_BASE_URL=http://127.0.0.1:8742
claude
```

### Codex (OpenAI)

```bash
# Start the proxy
zentinelle-agent proxy --endpoint http://localhost:8080 --key sk_agent_your_key --provider openai
# Then in another terminal:
export OPENAI_BASE_URL=http://127.0.0.1:8742
codex
```

### Gemini

```bash
# Start the proxy
zentinelle-agent proxy --endpoint http://localhost:8080 --key sk_agent_your_key --provider google
# Then in another terminal:
export GOOGLE_API_BASE=http://127.0.0.1:8742
# Launch your Gemini agent
```

---

## Hooks mode (Claude Code only)

Hooks intercept tool calls at the Claude Code layer:

- **PreToolUse** — calls `/api/zentinelle/v1/evaluate` before every tool invocation. If Zentinelle blocks the action (exit code 2), Claude Code shows the reason and skips the tool.
- **PostToolUse** — emits an audit event to `/api/zentinelle/v1/events` after every tool call. Fire-and-forget, never blocks.

### Setup

```bash
zentinelle-agent install \
  --endpoint http://localhost:8080 \
  --key sk_agent_your_key_here \
  --agent-id my-agent
```

Restart Claude Code to activate.

### Options

```
--endpoint      Zentinelle base URL (or ZENTINELLE_ENDPOINT env var)
--key           Agent API key      (or ZENTINELLE_KEY env var)
--agent-id      Agent identifier   (default: claude-code)
--project-dir   Target project directory (default: current directory)
--fail-open     Allow tool calls when Zentinelle is unreachable
--mode          both | pre | post  (default: both)
```

### Uninstall / Status

```bash
zentinelle-agent uninstall
zentinelle-agent status
```

---

## Proxy mode (all agents)

The proxy routes all LLM API calls through Zentinelle for policy enforcement before they reach the upstream provider.

```
Agent → http://127.0.0.1:8742 → Zentinelle /proxy/<provider>/ → provider API
         (local proxy)           (policy evaluation)
```

### Start the proxy

```bash
zentinelle-agent proxy \
  --endpoint http://localhost:8080 \
  --key sk_agent_your_key_here \
  --provider anthropic   # or openai, google
```

### Supported providers

| Provider | Upstream | Agent env var |
|----------|----------|---------------|
| `anthropic` | api.anthropic.com | `ANTHROPIC_BASE_URL` |
| `openai` | api.openai.com | `OPENAI_BASE_URL` |
| `google` | generativelanguage.googleapis.com | `GOOGLE_API_BASE` |

### How it works

1. Receives the request from your agent (with the real provider API key)
2. Injects `X-Zentinelle-Key` to identify the agent
3. Forwards to Zentinelle's proxy endpoint
4. Zentinelle evaluates policies (rate limits, model restrictions, content filters)
5. Streams the response back (SSE/streaming supported)

---

## Environment variables

| Variable | Description |
|----------|-------------|
| `ZENTINELLE_ENDPOINT` | Zentinelle base URL |
| `ZENTINELLE_KEY` | Agent API key |
| `ZENTINELLE_AGENT_ID` | Agent identifier |
| `ZENTINELLE_FAIL_OPEN` | Set to `1` to allow tool calls when Zentinelle is offline |

---

## Requirements

- Python 3.9+
- `httpx>=0.24.0` (for proxy streaming)
- A running Zentinelle instance
