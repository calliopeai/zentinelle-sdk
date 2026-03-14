# gemini.md — Zentinelle SDK (Gemini)

> Read [bootstrap.md](bootstrap.md) for full technical context.
> Read [memory.md](memory.md) for project decisions and current state.

## Gemini-Specific Notes

- Multi-language repo — Python, TypeScript, Go, Java, C#, and framework plugins
- Each language subdirectory has its own toolchain and tests
- Core interface: `register()`, `evaluate()`, `emit()`, `get_config()`, `get_secrets()`, `heartbeat()`
- Key design constraints: fail-open mode, circuit breaker, event buffering, config caching
- Do not commit calliope.md (it is gitignored and contains internal Calliope context)
