# Zentinelle SDK — Memory

> Persistent decisions and project state. See [bootstrap.md](bootstrap.md) for technical reference.

---

## What This Is

Multi-language SDK for the Zentinelle Agent GRC (Governance, Risk, Compliance) service. Provides AI agents with policy enforcement, secrets management, and observability across any AI framework.

Published as:
- `zentinelle` on PyPI (Python)
- `zentinelle` on npm (TypeScript)
- `github.com/calliopeai/zentinelle-go` Go module
- `ai.zentinelle:zentinelle-sdk` on Maven Central (Java)
- NuGet package (C#)

---

## Current State (as of 2026-03)

| Language | Status | Notes |
|----------|--------|-------|
| Python | Stable | Full client, tests, published to PyPI |
| TypeScript | Stable | Full client, tests, published to npm |
| Go | Complete | Full client with goroutine-safe circuit breaker |
| Java | Complete | Maven-based, Apache 2.0 license |
| C# | Complete | .NET solution |
| Plugins | In progress | See plugin status below |

### Plugin Status

| Plugin | Priority | Status |
|--------|----------|--------|
| LangChain | P0 | In progress — Python callback handler scaffolded |
| CrewAI | P0 | In progress — Python package scaffolded |
| Vercel AI SDK | P0 | In progress — TypeScript package scaffolded |
| LlamaIndex | P1 | Planned |
| n8n | P1 | Planned |
| MS Agent Framework | P1 | Planned |

---

## Design Decisions

### Fail-Open Default: False

Fail-open defaults to `False` — agents are blocked (not allowed) when Zentinelle is unreachable. Operators explicitly opt into fail-open for non-critical governance paths. The `fail_open` flag is always present in `EvaluateResult` so callers can detect degraded operation.

### Circuit Breaker

All languages implement a 3-state circuit breaker (CLOSED → OPEN → HALF_OPEN). Default thresholds: 5 failures to open, 30-second recovery timeout. Rate limit errors (429) are not counted as failures — they are service-side throttling, not outages.

### Event Buffering

Events are fire-and-forget from the caller's perspective. The SDK buffers internally and flushes in batches. Hard cap at max(buffer_size × 10, 1000) to prevent memory leaks; oldest events are dropped under sustained load. On flush failure, events are re-queued unless the buffer is full.

### Config Caching

Config cached 5 minutes, secrets cached 60 seconds. Thread-safe with copy-on-read to prevent external mutation. Heartbeat triggers automatic refresh when `config_changed: true`.

### Auth Errors are Not Retried

401/403 responses propagate immediately without retry — they indicate a configuration problem, not a transient failure.

### HTTPS Enforced

The endpoint must use HTTPS (localhost/127.0.0.1 exempt for local development). The API key is sent in the `X-Zentinelle-Key` header.

### Thread Safety

Python: threading.Lock for buffer and cache. Go: sync.RWMutex with separate locks for state, buffer, secrets cache, and config cache. TypeScript: single-threaded event loop, `flushInProgress` guard to prevent concurrent flushes.

---

## Relationship to Other Repos

### zentinelle.git

The backend service that the SDK talks to. The SDK is the client; zentinelle.git is the server. They are separate repos.

### client-cove

The SDK is currently embedded as a git submodule in client-cove:
- `backend/sentinel/sdk` — legacy path (sentinel was the previous service name)
- `backend/zentinelle/sdk` — current path

Migration plan: move to pip/npm dependency (`zentinelle` package) so client-cove installs from PyPI/npm rather than embedding the submodule.

---

## Knowledge System

This repo uses the Calliope federated knowledge system schema:

| File | Purpose |
|------|---------|
| `bootstrap.md` | Canonical technical reference (agent-agnostic, public) |
| `memory.md` | This file — persistent decisions and state |
| `CLAUDE.md` | Thin shim → bootstrap + memory (Claude Code) |
| `agents.md` | Thin shim → bootstrap + memory (generic agents) |
| `gemini.md` | Thin shim → bootstrap + memory (Gemini) |
| `calliope.md` | Internal-only shim (gitignored) — Calliope-specific wiring |
