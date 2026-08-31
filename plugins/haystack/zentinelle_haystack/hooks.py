"""A `before_tool` hook for `haystack.components.agents.Agent`.

The Agent runs its hooks with no exception handling around them, so raising
here aborts the run. Haystack's own `ConfirmationHook` instead rejects by
rewriting the message history, which returns the refusal to the model as a tool
result; that is the right shape for a human declining an action and the wrong
one for a policy denial, because it lets the agent try another route to the
same thing.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .errors import PolicyViolationError

logger = logging.getLogger(__name__)

AGENT_TYPE = "haystack"


class ZentinelleToolHook:
    """Checks every pending tool call before the Agent runs any of them.

    Register with `Agent(..., hooks={"before_tool": [ZentinelleToolHook(client)]})`.
    """

    # The Agent validates this at construction: the pending tool calls only
    # exist at this point, between the model asking for them and them running.
    allowed_hook_points = ("before_tool",)

    def __init__(
        self,
        client: Any,
        user_id: Optional[str] = None,
        fail_open: bool = False,
    ):
        self.client = client
        self.user_id = user_id
        self.fail_open = fail_open

    def run(self, state) -> None:
        # `state.data` rather than `state.get`, which deep-copies; the same
        # reason Haystack's own hook reads it this way.
        messages = state.data.get("messages") or []
        if not messages:
            return

        tool_calls = getattr(messages[-1], "tool_calls", None) or []
        for call in tool_calls:
            self._check(getattr(call, "tool_name", None) or "unknown")

    async def run_async(self, state) -> None:
        self.run(state)

    def _check(self, name: str) -> None:
        try:
            result = self.client.can_call_tool(name, self.user_id)
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Tool check failed, allowing %s: %s", name, exc)
                return
            raise PolicyViolationError(
                f"Policy check for tool '{name}' failed and fail_open is off: {exc}"
            ) from exc

        if not result.allowed:
            raise PolicyViolationError(
                f"Tool '{name}' was refused by policy: "
                f"{result.reason or 'no reason given'}",
                result,
            )

        try:
            self.client.emit_tool_call(tool_name=name, user_id=self.user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record tool call: %s", exc)
