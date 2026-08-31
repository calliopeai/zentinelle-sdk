"""The plugin's one exception type.

Defined here rather than in each module because there were briefly two classes
called `PolicyViolationError`, one per module, and the package exported only
one of them. `except PolicyViolationError` after importing from the package
therefore caught generator denials and let tool denials through, which is the
worst possible shape for a governance error: it looks handled and is not.
"""
from __future__ import annotations

from typing import Any


class PolicyViolationError(Exception):
    """A request, reply or tool call was refused by policy."""

    def __init__(self, message: str, result: Any = None):
        super().__init__(message)
        self.result = result
