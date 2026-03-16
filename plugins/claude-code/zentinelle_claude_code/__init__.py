"""
Zentinelle Claude Code Integration

Two modes:

  Proxy mode  — set ANTHROPIC_BASE_URL to the local Zentinelle proxy.
                Full policy enforcement on every Anthropic API call before it
                leaves the machine. Requires `zentinelle-claude-code proxy`.

  Hooks mode  — Claude Code PreToolUse / PostToolUse hooks call Zentinelle for
                policy evaluation and audit. Tool calls can be blocked in real
                time. Install with `zentinelle-claude-code install`.
"""
from ._version import __version__

__all__ = ["__version__"]
