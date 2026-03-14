# Zentinelle SDK — Bootstrap Reference

> See [memory.md](memory.md) for project decisions and current state.

Canonical technical reference for the Zentinelle SDK — a multi-language client library for the Zentinelle Agent GRC (Governance, Risk, Compliance) service. Agent-agnostic and public.

---

## What This Is

The Zentinelle SDK provides AI agents with:
- **Policy enforcement** — evaluate whether an action is allowed before executing it
- **Secrets management** — retrieve secrets the agent is authorized to use
- **Observability** — emit events for telemetry, audit logging, and compliance
- **Lifecycle management** — register on startup, heartbeat while running, shutdown cleanly

The SDK talks to a Zentinelle service instance (cloud at `api.zentinelle.ai` or self-hosted). It is designed to be embedded directly in AI agent code across any framework.

---

## Repo Structure

```
zentinelle-sdk/
├── python/                  # Python SDK (PyPI: zentinelle)
│   ├── zentinelle/
│   │   ├── __init__.py
│   │   ├── _version.py      # version string
│   │   ├── client.py        # ZentinelleClient (main entry point)
│   │   └── types.py         # dataclasses: EvaluateResult, PolicyConfig, etc.
│   ├── tests/
│   │   └── test_client.py
│   └── pyproject.toml       # hatchling build, ruff, mypy, pytest config
├── typescript/              # TypeScript SDK (npm: zentinelle)
│   ├── src/
│   │   ├── index.ts         # public exports
│   │   ├── client.ts        # ZentinelleClient class
│   │   ├── types.ts         # TypeScript interfaces
│   │   ├── errors.ts        # error classes
│   │   └── resilience.ts    # RetryConfig, CircuitBreaker
│   ├── tests/
│   │   └── client.test.ts   # vitest tests
│   ├── package.json         # tsup build, vitest, eslint
│   └── tsconfig.json
├── go/                      # Go SDK (module: github.com/calliopeai/zentinelle-go)
│   ├── zentinelle/
│   │   ├── client.go        # Client struct, all methods
│   │   ├── circuit_breaker.go
│   │   ├── errors.go        # error types
│   │   └── types.go         # Event, ModelUsage, PolicyConfig, etc.
│   └── go.mod
├── java/                    # Java SDK (Maven: ai.zentinelle:zentinelle-sdk)
│   ├── src/main/java/ai/zentinelle/
│   │   └── Zentinelle/      # ZentinelleClient class
│   └── pom.xml
├── csharp/                  # C# SDK
│   ├── src/Zentinelle/      # ZentinelleClient class
│   └── Zentinelle.sln
├── plugins/                 # Framework-specific integrations
│   ├── langchain/           # Python — LangChain callback handlers
│   ├── crewai/              # Python — CrewAI governance
│   ├── llamaindex/          # Python — LlamaIndex RAG guardrails
│   ├── vercel-ai/           # TypeScript — Vercel AI SDK middleware
│   ├── ms-agent-framework/  # Python — Microsoft Agent Framework extensions
│   └── n8n/                 # n8n workflow automation nodes
└── templates/               # Scaffolding for new plugins
```

---

## Core API

All language implementations expose the same logical interface. Method names follow language conventions (snake_case for Python/Go, camelCase for TypeScript/Java/C#).

### Client Initialization

**Python**
```python
from zentinelle import ZentinelleClient

client = ZentinelleClient(
    api_key="sk_agent_...",      # required; prefixes: sk_agent_, sk_test_, sk_live_, znt_
    agent_type="langchain",      # required; identifies the framework type
    endpoint="https://api.zentinelle.ai",  # optional; defaults to cloud
    agent_id="my-agent",         # optional; generated on register() if omitted
    org_id=None,                 # optional; derived from API key if not provided
    fail_open=False,             # if True, allow all actions when service is unreachable
    auto_heartbeat=True,         # start background heartbeat thread
    heartbeat_interval=60,       # seconds between heartbeats
    event_buffer_size=100,       # events buffered before auto-flush
    event_flush_interval=5,      # seconds between background flushes
    config_cache_ttl=300,        # config cache TTL in seconds
    secrets_cache_ttl=60,        # secrets cache TTL in seconds
)
```

**TypeScript**
```typescript
import { ZentinelleClient } from 'zentinelle';

const client = new ZentinelleClient({
  apiKey: 'sk_agent_...',
  agentType: 'langchain',
  endpoint: 'https://api.zentinelle.ai',  // optional
  failOpen: false,
  autoHeartbeat: true,
  heartbeatInterval: 60000,  // ms
  bufferSize: 100,
  flushInterval: 5000,       // ms
});
```

**Go**
```go
import "github.com/calliopeai/zentinelle-go/zentinelle"

client, err := zentinelle.NewClient(zentinelle.Config{
    APIKey:    "sk_agent_...",
    AgentType: "go-agent",
    FailOpen:  false,
})
defer client.Shutdown()
```

### register()

Register the agent on startup. Returns agent ID, config, and initial policies. Must be called before `evaluate()`, `get_config()`, or `get_secrets()`.

```python
result = client.register(
    capabilities=["chat", "tools", "code"],
    metadata={"version": "1.0.0", "cluster": "us-east-1"},
    name="My Agent",
)
# result.agent_id, result.config, result.policies
```

API endpoint: `POST /api/v1/agents/register`

### evaluate()

Evaluate policies for an action before executing it. This is the primary policy enforcement point.

```python
result = client.evaluate(
    "tool_call",
    user_id="user123",
    context={"tool": "web_search"},
)
if not result.allowed:
    raise PermissionError(result.reason)
```

Convenience wrappers: `can_call_tool(tool_name, user_id)`, `can_use_model(model, provider)`.

In fail-open mode, returns `EvaluateResult(allowed=True, fail_open=True)` when the service is unreachable. The `fail_open` flag is always set so callers can detect degraded operation.

API endpoint: `POST /api/v1/evaluate`

### emit()

Emit a governance event. Events are buffered in memory and flushed in batches to avoid blocking the agent's hot path.

```python
client.emit(
    event_type="tool_call",
    payload={"tool": "web_search", "duration_ms": 450},
    category="audit",   # telemetry | audit | alert | compliance
    user_id="user123",
)
# Convenience methods:
client.emit_tool_call("web_search", user_id="user123", duration_ms=450)
client.emit_model_request("openai", "gpt-4o", input_tokens=800, output_tokens=300)
client.track_usage(ModelUsage.from_openai(openai_response))
```

API endpoint: `POST /api/v1/events` (batch)

### get_config()

Fetch agent config and policies. Cached (default TTL: 5 minutes).

```python
config = client.get_config()           # uses cache
config = client.get_config(force_refresh=True)  # bypass cache
# config.config (dict), config.policies (list[PolicyConfig])
```

API endpoint: `GET /api/v1/agents/{agent_id}/config`

### get_secrets()

Fetch secrets this agent is authorized to access. Cached (default TTL: 60 seconds). Returns a copy — mutations do not affect the cache.

```python
secrets = client.get_secrets()
openai_key = secrets["OPENAI_API_KEY"]
# Or single key:
key = client.get_secret("OPENAI_API_KEY", default=None)
```

API endpoint: `GET /api/v1/agents/{agent_id}/secrets`

### heartbeat()

Send a heartbeat. Called automatically by the background thread when `auto_heartbeat=True`. If the heartbeat response indicates config has changed, the client automatically refreshes config.

```python
result = client.heartbeat(status="healthy", metrics={"queue_depth": 5})
# result.acknowledged, result.config_changed, result.next_heartbeat_seconds
```

API endpoint: `POST /api/v1/heartbeat`

### shutdown()

Flush remaining events, stop background threads, clear sensitive data from memory.

```python
client.shutdown()
# Or use as context manager:
with ZentinelleClient(...) as client:
    ...
```

---

## HTTP Transport

All requests use:
- Header `X-Zentinelle-Key: <api_key>`
- Header `X-Zentinelle-Org: <org_id>` (if set)
- Base URL: `<endpoint>/api/v1`
- HTTPS enforced (localhost/127.0.0.1 exempt for local dev)

Error handling:
- `401` → `ZentinelleAuthError` (no retry)
- `403` → `ZentinelleAuthError` (no retry)
- `429` → `ZentinelleRateLimitError` (no retry; rate limits are not circuit-breaker failures)
- `5xx` → `ZentinelleConnectionError` (retry with backoff, trip circuit breaker)
- Network error → `ZentinelleConnectionError` (retry with backoff, trip circuit breaker)

---

## Key Design Constraints

### Fail-Open

When `fail_open=True`, the SDK allows all actions when the Zentinelle service is unreachable rather than blocking. This is appropriate for non-critical governance paths where availability > security. Always `False` by default.

The `evaluate()` response always carries a `fail_open` flag so callers can detect when they are running in degraded mode.

### Circuit Breaker

Three states: CLOSED (normal) → OPEN (service down, fail fast) → HALF_OPEN (testing recovery).

Defaults:
- Failure threshold: 5 consecutive failures → OPEN
- Recovery timeout: 30 seconds before attempting HALF_OPEN
- Half-open max calls: 3 successes → CLOSED

### Event Buffering

Events are queued in memory and flushed in batches. The buffer has two size limits:
- `event_buffer_size` (default: 100) — triggers an immediate flush when reached
- `max_buffer_size` = max(buffer_size × 10, 1000) — hard cap; oldest events are dropped if exceeded

Background flush runs every `event_flush_interval` seconds (default: 5s). On transient flush failure, events are re-queued. On auth failure during flush, events are dropped (configuration problem, not transient).

### Config Caching

Config is cached in memory with a TTL (default: 5 minutes for config, 60 seconds for secrets). Thread-safe. Returns a copy to prevent external mutation from corrupting the cache.

When a heartbeat response indicates `config_changed: true`, config is automatically refreshed.

---

## Running Tests

### Python

```bash
cd python/
pip install -e ".[dev]"
pytest tests/
pytest --cov=zentinelle tests/   # with coverage
ruff check zentinelle/           # lint
mypy zentinelle/                 # type check
```

### TypeScript

```bash
cd typescript/
npm install
npm test              # vitest
npm run lint          # eslint
npm run build         # tsup → dist/
```

### Go

```bash
cd go/
go test ./...
go vet ./...
```

### Java

```bash
cd java/
mvn test
mvn package          # builds JAR
```

### C#

```bash
cd csharp/
dotnet test
dotnet build
```

---

## Building and Publishing

### Python (PyPI)

```bash
cd python/
pip install build twine
python -m build                             # builds dist/zentinelle-*.whl and .tar.gz
twine upload dist/*                         # publish to PyPI
```

Version is in `python/zentinelle/_version.py` and `python/pyproject.toml`.

### TypeScript (npm)

```bash
cd typescript/
npm run build          # runs tsup, outputs to dist/
npm publish            # publishes to npm as "zentinelle"
```

Version is in `typescript/package.json`.

### Go

Go modules are consumed directly from git. Tag the release:
```bash
git tag go/v0.1.0
git push origin go/v0.1.0
```

Module path: `github.com/calliopeai/zentinelle-go`

### Java (Maven Central)

```bash
cd java/
mvn deploy -P release   # requires GPG signing and Sonatype credentials
```

GroupId: `ai.zentinelle`, ArtifactId: `zentinelle-sdk`

### C# (NuGet)

```bash
cd csharp/
dotnet pack -c Release
dotnet nuget push src/Zentinelle/bin/Release/*.nupkg --api-key $NUGET_API_KEY
```

---

## Plugin Development Guide

Plugins live in `plugins/<name>/` and wrap the core SDK to provide framework-native ergonomics.

### Structure (Python plugin example)

```
plugins/langchain/
├── pyproject.toml          # depends on zentinelle >= 0.1.0
├── zentinelle_langchain/
│   ├── __init__.py
│   ├── callback.py         # ZentinelleCallbackHandler
│   └── guardrails.py       # input/output guardrail classes
└── tests/
    └── test_callback.py
```

### Structure (TypeScript plugin example)

```
plugins/vercel-ai/
├── package.json            # depends on zentinelle
├── src/
│   ├── index.ts
│   └── middleware.ts       # wrapLanguageModel(), wrapTextGeneration()
└── tsconfig.json
```

### Plugin contract

A plugin must:
1. Accept a `ZentinelleClient` instance (do not construct one internally)
2. Call `client.evaluate()` before framework-level actions
3. Call `client.emit()` after framework-level events (tool calls, model requests, etc.)
4. Not swallow `ZentinelleAuthError` — propagate it to the caller
5. Respect `result.fail_open` — log a warning if running in degraded mode

### Priority plugins

| Plugin | Status | Languages |
|--------|--------|-----------|
| LangChain | In progress | Python |
| CrewAI | In progress | Python |
| Vercel AI SDK | In progress | TypeScript |
| LlamaIndex | Planned | Python |
| n8n | Planned | TypeScript/JS |
| MS Agent Framework | Planned | Python |

---

## Versioning and Release Process

All language packages are versioned together at `0.1.0`. The release process:

1. Bump version in:
   - `python/pyproject.toml` → `[project] version`
   - `python/zentinelle/_version.py` → `__version__`
   - `typescript/package.json` → `"version"`
   - `java/pom.xml` → `<version>`
   - `go/zentinelle/client.go` → User-Agent header string

2. Commit: `release: v0.2.0`

3. Tag: `git tag v0.2.0 && git push origin v0.2.0`

4. Publish each package (see Building and Publishing above)

The Go module uses a separate tag prefix (`go/vX.Y.Z`) per Go module conventions.

---

## API Key Format

Valid prefixes: `sk_agent_`, `sk_test_`, `sk_live_`, `znt_`

The SDK logs a warning (but does not error) if the key doesn't match a known prefix.

---

## Links

- Docs: https://docs.zentinelle.ai
- API Reference: https://docs.zentinelle.ai/api
- Integration Guides: https://docs.zentinelle.ai/integrations
- GitHub: https://github.com/calliopeai/zentinelle-sdk
- npm: https://www.npmjs.com/package/zentinelle
- PyPI: https://pypi.org/project/zentinelle/
