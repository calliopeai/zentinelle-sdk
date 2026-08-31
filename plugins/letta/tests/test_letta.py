"""Tests for the Zentinelle Letta plugin.

Letta's client is not installed, and unlike the other plugins here nothing
about it needs stubbing at import time: the plugin wraps whatever client it is
handed.

These tests pin the honest boundary as much as the behaviour. Letta runs the
agent loop on a server, so the only thing this can enforce is whether a message
is sent at all. `test_the_ungoverned_path_is_still_reachable` exists to record
that limitation rather than let someone discover it.
"""

import types
from dataclasses import dataclass
from typing import Optional

import pytest

from zentinelle_letta import (
    GovernedLetta,
    PolicyViolationError,
    require_tool_approval,
)


@dataclass
class FakeResult:
    allowed: bool
    reason: Optional[str] = None


class FakeZentinelle:
    def __init__(self, allowed=True, reason=None, raises=None):
        self.allowed = allowed
        self.reason = reason
        self.raises = raises
        self.evaluated = []
        self.usage = []
        self.events = []

    def evaluate(self, action, user_id=None, context=None):
        if self.raises:
            raise self.raises
        self.evaluated.append((action, context))
        return FakeResult(self.allowed, self.reason)

    def track_usage(self, usage):
        self.usage.append(usage)

    def emit(self, event_type, payload=None, category=None, user_id=None):
        self.events.append((event_type, payload or {}))


class FakeBlock:
    def __init__(self, label, value):
        self.label = label
        self.value = value


class FakeLetta:
    """Just enough of letta_client.Letta's resource tree."""

    def __init__(self, blocks=None, usage=None):
        self.sent = []
        self._blocks = list(blocks or [])
        self._usage = usage or types.SimpleNamespace(
            prompt_tokens=40, completion_tokens=8
        )
        self.approvals = []
        outer = self

        class _Messages:
            def create(self, agent_id, **kwargs):
                outer.sent.append((agent_id, kwargs))
                # Standing in for the server editing memory during the run.
                for block in outer._blocks:
                    if block.label == "human":
                        block.value = "changed by the run"
                return types.SimpleNamespace(usage=outer._usage, messages=[])

        class _Blocks:
            def list(self, agent_id):
                return [FakeBlock(b.label, b.value) for b in outer._blocks]

        class _Tools:
            def update_approval(self, name, agent_id=None, body_requires_approval=None):
                outer.approvals.append((name, agent_id, body_requires_approval))

        self.agents = types.SimpleNamespace(
            messages=_Messages(), blocks=_Blocks(), tools=_Tools()
        )
        self.some_other_api = "reachable"


# ---- the one thing it can enforce --------------------------------------


def test_a_denied_message_is_never_sent():
    letta = FakeLetta()
    zen = FakeZentinelle(allowed=False, reason="contains a credential")

    with pytest.raises(PolicyViolationError) as excinfo:
        GovernedLetta(letta, zen).send_message(
            agent_id="agent-1", messages=[{"content": "here is my key"}]
        )

    assert letta.sent == [], "the message was sent despite being refused"
    assert "contains a credential" in str(excinfo.value)


def test_an_allowed_message_is_sent():
    letta = FakeLetta()
    governed = GovernedLetta(letta, FakeZentinelle(allowed=True))

    governed.send_message(agent_id="agent-1", messages=[{"content": "hello"}])

    assert len(letta.sent) == 1
    assert letta.sent[0][0] == "agent-1"


def test_an_unreachable_control_plane_refuses_by_default():
    letta = FakeLetta()
    zen = FakeZentinelle(raises=RuntimeError("control plane unreachable"))

    with pytest.raises(PolicyViolationError):
        GovernedLetta(letta, zen).send_message(agent_id="a", messages=[])

    assert letta.sent == []


def test_fail_open_sends_when_the_check_fails():
    letta = FakeLetta()
    zen = FakeZentinelle(raises=RuntimeError("down"))

    GovernedLetta(letta, zen, fail_open=True).send_message(agent_id="a", messages=[])

    assert len(letta.sent) == 1


# ---- the boundary -------------------------------------------------------


def test_the_ungoverned_path_is_still_reachable():
    """Attribute access falls through, and that is a documented caveat.

    There is no interceptor underneath, so calling the client's own method
    bypasses the check. The README says so; this pins it, so that if a future
    change makes the wrapper appear to cover everything, the claim and the code
    are checked against each other.
    """
    letta = FakeLetta()
    governed = GovernedLetta(letta, FakeZentinelle(allowed=False, reason="no"))

    governed.agents.messages.create("agent-1", messages=[{"content": "hi"}])

    assert len(letta.sent) == 1
    assert governed.some_other_api == "reachable"


# ---- recording ----------------------------------------------------------


def test_token_usage_is_recorded():
    letta = FakeLetta()
    zen = FakeZentinelle()

    GovernedLetta(letta, zen).send_message(agent_id="a", messages=[])

    assert zen.usage[0].input_tokens == 40
    assert zen.usage[0].output_tokens == 8


def test_a_changed_memory_block_is_reported():
    letta = FakeLetta(blocks=[FakeBlock("human", "original"),
                              FakeBlock("persona", "steady")])
    zen = FakeZentinelle()

    GovernedLetta(letta, zen, audit_memory=True).send_message(
        agent_id="agent-1", messages=[]
    )

    changed = [p["block"] for e, p in zen.events if e == "memory_block_changed"]
    assert changed == ["human"], "only the block that actually changed is reported"


def test_memory_auditing_is_off_by_default():
    """It costs two extra round trips per call, so it is opt-in."""
    letta = FakeLetta(blocks=[FakeBlock("human", "original")])
    zen = FakeZentinelle()

    GovernedLetta(letta, zen).send_message(agent_id="a", messages=[])

    assert [e for e, _ in zen.events if e == "memory_block_changed"] == []


# ---- Letta's own gate ---------------------------------------------------


def test_require_tool_approval_sets_the_server_side_flag():
    letta = FakeLetta()

    require_tool_approval(letta, "agent-1", ["delete_records", "wire_transfer"])

    assert letta.approvals == [
        ("delete_records", "agent-1", True),
        ("wire_transfer", "agent-1", True),
    ]
