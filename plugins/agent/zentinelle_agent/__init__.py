"""
Zentinelle Agent Integration

Two modes:

  Proxy mode  — set your provider's base URL to the local Zentinelle proxy.
                Full policy enforcement on every API call before it
                leaves the machine. Requires `zentinelle-agent proxy`.

  Hooks mode  — Claude Code PreToolUse / PostToolUse hooks call Zentinelle for
                policy evaluation and audit. Tool calls can be blocked in real
                time. Install with `zentinelle-agent install`.
"""
from ._version import __version__

__all__ = ["__version__"]
