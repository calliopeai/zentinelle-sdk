# zentinelle-claude-code

Zentinelle governance integration for [Claude Code](https://claude.ai/code) sessions.

Two complementary modes — use one or both:

| Mode | What it does | Enforcement level |
|------|-------------|-------------------|
| **Hooks** | Intercepts every tool call via Claude Code's PreToolUse/PostToolUse hooks | Tool-level (can block individual tool calls) |
| **Proxy** | Routes all Anthropic API calls through Zentinelle | API-level (full policy enforcement before any request reaches Anthropic) |

---

## Installation

```bash
pip install zentinelle-claude-code
```

---

## Hooks mode

Hooks intercept tool calls at the Claude Code layer:

- **PreToolUse** — calls `/api/zentinelle/v1/evaluate` before every tool invocation. If Zentinelle blocks the action (exit code 2), Claude Code shows the reason to the user and does not execute the tool.
- **PostToolUse** — emits an audit event to `/api/zentinelle/v1/events` after every tool call. Fire-and-forget, never blocks.

### Setup

```bash
zentinelle-claude-code install \
  --endpoint http://localhost:8000 \
  --key sk_agent_your_key_here \
  --agent-id my-claude-session
```

This writes hooks into `.claude/settings.json` in your current directory:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "ZENTINELLE_ENDPOINT='http://localhost:8000' ZENTINELLE_KEY='sk_agent_...' ZENTINELLE_AGENT_ID='my-claude-session' python3 '/path/to/pre_tool.py'"
          }
        ]
      }
    ],
    "PostToolUse": [...]
  }
}
```

Restart Claude Code to activate.

### Options

```
--endpoint      Zentinelle base URL (or ZENTINELLE_ENDPOINT env var)
--key           Agent API key      (or ZENTINELLE_KEY env var)
--agent-id      Agent identifier   (default: claude-code)
--project-dir   Target project directory (default: current directory)
--fail-open     Allow tool calls when Zentinelle is unreachable
                (default: block when unreachable for safety)
--mode          both | pre | post  (default: both)
```

### Uninstall

```bash
zentinelle-claude-code uninstall
```

### Check status

```bash
zentinelle-claude-code status
```

---

## Proxy mode

The proxy routes all Anthropic API calls through Zentinelle before they reach `api.anthropic.com`. Zentinelle evaluates policies (model restrictions, budget limits, content filters, etc.) on every request.

```
Claude Code → http://127.0.0.1:8742 → Zentinelle proxy → api.anthropic.com
               (local proxy)            /zentinelle/proxy/anthropic/
```

### Start the proxy

```bash
zentinelle-claude-code proxy \
  --endpoint http://localhost:8000 \
  --key sk_agent_your_key_here
```

Output:
```
Zentinelle proxy started on http://127.0.0.1:8742
Forwarding to: http://localhost:8000/zentinelle/proxy/anthropic

Configure Claude Code:
  export ANTHROPIC_BASE_URL=http://127.0.0.1:8742
```

In a new terminal (or added to your shell profile):

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8742
claude  # or continue your existing Claude Code session
```

### Options

```
--endpoint      Zentinelle base URL (or ZENTINELLE_ENDPOINT env var)
--key           Agent API key      (or ZENTINELLE_KEY env var)
--port          Local proxy port   (default: 8742)
--host          Bind address       (default: 127.0.0.1)
```

### How it works

The proxy:
1. Receives the request from Claude Code (which includes your real `Authorization: Bearer sk-ant-...` header)
2. Injects `X-Zentinelle-Key: <your-agent-key>` to identify the agent
3. Forwards to `{ZENTINELLE_ENDPOINT}/zentinelle/proxy/anthropic/`
4. Zentinelle strips `X-Zentinelle-Key`, evaluates policies, and proxies to `api.anthropic.com`
5. Streams the response back (SSE/streaming supported)

---

## Using both modes together

Hooks give you tool-call-level observability and blocking. The proxy gives you API-level enforcement. They complement each other well:

```bash
# Terminal 1: start the proxy
zentinelle-claude-code proxy --endpoint http://localhost:8000 --key sk_agent_...

# Terminal 2: install hooks and point Claude Code at the proxy
zentinelle-claude-code install --endpoint http://localhost:8000 --key sk_agent_...
export ANTHROPIC_BASE_URL=http://127.0.0.1:8742
claude
```

---

## Environment variables

All options can be set via environment variables:

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
- Claude Code CLI
- A running Zentinelle instance
