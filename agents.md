# agents.md — Zentinelle SDK (Generic Agents)

> Read [bootstrap.md](bootstrap.md) for full technical context.
> Read [memory.md](memory.md) for project decisions and current state.

## Agent Notes

- This is a multi-language SDK repo: Python, TypeScript, Go, Java, C#, plus framework plugins
- Each language subdirectory is self-contained with its own build toolchain
- Core interface: `register()`, `evaluate()`, `emit()`, `get_config()`, `get_secrets()`, `heartbeat()`
- All languages share the same API contract and default values
- Do not modify generated files in `dist/` or `build/` directories
