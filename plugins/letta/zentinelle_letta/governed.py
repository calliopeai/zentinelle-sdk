"""Zentinelle governance for Letta (MemGPT).

Read this before using it, because Letta is not like the other harnesses here.

`letta-client` is a generated REST wrapper around a Letta *server*. The agent
loop, the model call, the tool execution and the memory edits all happen on the
server, in another process. The client has no hook, middleware or interceptor:
by the time anything interesting happens, the client is waiting on a socket.

So there is exactly one honest enforcement point, and it is the call site. A
`GovernedLetta` wraps the client and checks policy before it sends a message.
That is real enforcement for the request, because the request genuinely does
not leave the process if policy refuses it. It is *not* enforcement for
anything the server then does: a tool the agent calls mid-run, or a memory
block it rewrites, happens server-side after the request was allowed, and no
client can veto it.

What the plugin therefore offers:

- **enforced**: whether a message may be sent at all
- **recorded**: token usage, which the server returns on the response
- **recorded, after the fact**: memory-tier changes, by snapshotting blocks
  around a call and reporting the difference

What it does not offer, and what no client-side integration can:

- blocking an individual tool call. Letta's own mechanism is the server-side
  `requires_approval` flag plus an approval round trip, which is a workflow
  rather than a policy engine. `require_tool_approval()` below sets that flag
  for you; it does not make Zentinelle the one deciding.
- reacting to a memory edit as it happens. There is no event, webhook or
  stream. The diff below is polling, and a run that edits a block twice looks
  like one edit.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

AGENT_TYPE = "letta"

_CONTENT_LIMIT = 4000


class PolicyViolationError(Exception):
    """A message was refused by policy before being sent."""

    def __init__(self, message: str, result: Any = None):
        super().__init__(message)
        self.result = result


def _summarise(messages, limit: int = _CONTENT_LIMIT) -> str:
    if isinstance(messages, str):
        return messages[:limit]
    parts = []
    for message in list(messages or [])[-4:]:
        if isinstance(message, dict):
            content = message.get("content")
        else:
            content = getattr(message, "content", None)
        if isinstance(content, str):
            parts.append(content)
        elif content is not None:
            parts.append(str(content))
    return "\n".join(parts)[:limit]


class GovernedLetta:
    """A Letta client whose messages are checked before they are sent.

        from letta_client import Letta
        governed = GovernedLetta(Letta(api_key=...), zentinelle_client)
        response = governed.send_message(agent_id="agent-1", messages=[...])

    Attribute access falls through to the wrapped client, so everything else
    the SDK offers still works. That fall-through is also the honest caveat:
    calling `governed.agents.messages.create(...)` directly reaches the
    ungoverned path, because there is no interceptor underneath to catch it.
    Use `send_message`.
    """

    def __init__(
        self,
        client: Any,
        zentinelle_client: Any,
        user_id: Optional[str] = None,
        evaluate_requests: bool = True,
        track_token_usage: bool = True,
        audit_memory: bool = False,
        fail_open: bool = False,
    ):
        self._client = client
        self.zentinelle = zentinelle_client
        self.user_id = user_id
        self.evaluate_requests = evaluate_requests
        self.track_token_usage = track_token_usage
        self.audit_memory = audit_memory
        self.fail_open = fail_open

    def __getattr__(self, name):
        return getattr(self.__dict__["_client"], name)

    # -- the governed call site -------------------------------------------

    def send_message(self, agent_id: str, **kwargs):
        """`client.agents.messages.create`, with a policy check in front."""
        if self.evaluate_requests:
            self._check(agent_id, kwargs.get("messages") or kwargs.get("input"))

        before = self._memory_snapshot(agent_id) if self.audit_memory else None

        response = self._client.agents.messages.create(agent_id, **kwargs)

        if self.track_token_usage:
            self._track(response)
        if self.audit_memory:
            self._report_memory_changes(agent_id, before)

        return response

    # -- internals --------------------------------------------------------

    def _check(self, agent_id: str, messages) -> None:
        try:
            result = self.zentinelle.evaluate(
                "model_request",
                self.user_id,
                {
                    "direction": "input",
                    "harness": AGENT_TYPE,
                    "agent": agent_id,
                    "content": _summarise(messages),
                },
            )
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Zentinelle check failed, allowing: %s", exc)
                return
            raise PolicyViolationError(
                f"Zentinelle policy check failed and fail_open is off: {exc}"
            ) from exc

        if not result.allowed:
            raise PolicyViolationError(
                f"Message refused by policy: {result.reason or 'no reason given'}",
                result,
            )

    def _track(self, response) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        try:
            from zentinelle import ModelUsage

            self.zentinelle.track_usage(
                ModelUsage(
                    provider="letta",
                    model="unknown",  # the server picks it; the response does not say
                    input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record model usage: %s", exc)

    def _memory_snapshot(self, agent_id: str) -> dict:
        """Core memory blocks, by label, as they are right now."""
        try:
            blocks = self._client.agents.blocks.list(agent_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read memory blocks: %s", exc)
            return {}
        return {
            getattr(b, "label", None) or getattr(b, "id", str(i)): getattr(b, "value", None)
            for i, b in enumerate(blocks or [])
        }

    def _report_memory_changes(self, agent_id: str, before: Optional[dict]) -> None:
        """Emit an event per block whose value changed across the call.

        A diff, not a hook. Two edits to one block during a run look like one
        change, and a block edited and then reverted looks like none.
        """
        if before is None:
            return
        after = self._memory_snapshot(agent_id)
        for label, value in after.items():
            if before.get(label) == value:
                continue
            try:
                self.zentinelle.emit(
                    "memory_block_changed",
                    {"harness": AGENT_TYPE, "agent": agent_id, "block": label},
                    category="audit",
                    user_id=self.user_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not record memory change: %s", exc)


def require_tool_approval(client: Any, agent_id: str, tool_names: Iterable[str]) -> None:
    """Set Letta's server-side approval flag on the named tools.

    This is Letta's own gate, not Zentinelle's: the server pauses and emits an
    approval request before running the tool, and something still has to answer
    it. It is here because it is the only thing that stops a Letta tool call,
    and a deployment that needs one should know the flag exists. It does not
    route the decision through Zentinelle policy.
    """
    for name in tool_names:
        client.agents.tools.update_approval(
            name, agent_id=agent_id, body_requires_approval=True
        )
