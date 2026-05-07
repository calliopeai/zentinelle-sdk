"""Tests for the Zentinelle CrewAI governance plugin."""

import sys
import time
import types
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fake CrewAI module hierarchy — we never install crewai, so we build just
# enough of the module tree for the plugin's imports to resolve.
# ---------------------------------------------------------------------------


def _install_crewai_stubs():
    """Inject minimal crewai stubs into sys.modules so zentinelle_crewai can import."""

    crewai_mod = types.ModuleType("crewai")

    class _Agent:
        def __init__(self, role="", goal="", backstory="", **kwargs):
            self.role = role
            self.goal = goal
            self.backstory = backstory

    class _Task:
        def __init__(self, description="", expected_output="", **kwargs):
            self.description = description
            self.expected_output = expected_output

    class _Crew:
        def __init__(self, agents=None, tasks=None, **kwargs):
            self.agents = agents or []
            self.tasks = tasks or []

        def kickoff(self, inputs=None):
            return "crew result"

    crewai_mod.Agent = _Agent
    crewai_mod.Task = _Task
    crewai_mod.Crew = _Crew

    # crewai.tools — BaseTool must be a pydantic BaseModel because
    # GovernedTool uses pydantic Field() descriptors that need model
    # machinery to resolve from FieldInfo to actual values.
    crewai_tools_mod = types.ModuleType("crewai.tools")

    from pydantic import BaseModel as _PydanticBase

    class _BaseTool(_PydanticBase):
        model_config = {"arbitrary_types_allowed": True}
        name: str = ""
        description: str = ""
        func: Any = None

    crewai_tools_mod.BaseTool = _BaseTool

    sys.modules["crewai"] = crewai_mod
    sys.modules["crewai.tools"] = crewai_tools_mod


# Install stubs before any zentinelle_crewai imports
_install_crewai_stubs()


# ---------------------------------------------------------------------------
# Fake zentinelle types — mirrors the SDK's dataclasses so the plugin code
# that constructs EvaluateResult / ModelUsage works correctly.
# ---------------------------------------------------------------------------


@dataclass
class _EvaluateResult:
    allowed: bool
    reason: Optional[str] = None
    policies: list = field(default_factory=list)
    policies_evaluated: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    context: dict = field(default_factory=dict)
    fail_open: bool = False
    requires_approval: bool = False
    approval_workflow_id: Optional[str] = None


@dataclass
class _ModelUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Optional[float] = None
    provider: str = ""


# Patch zentinelle.types so the plugin resolves these names
_zt_types = types.ModuleType("zentinelle.types")
_zt_types.EvaluateResult = _EvaluateResult
_zt_types.ModelUsage = _ModelUsage
sys.modules["zentinelle.types"] = _zt_types

_zt = types.ModuleType("zentinelle")
_zt.ZentinelleClient = MagicMock  # just needs to be importable
sys.modules["zentinelle"] = _zt

# Now safe to import the plugin
from zentinelle_crewai.callbacks import ZentinelleCrewCallback  # noqa: E402
from zentinelle_crewai.agent import GovernedAgent, GovernedAgentExecutor  # noqa: E402
from zentinelle_crewai.crew import GovernedCrew, PolicyViolationError  # noqa: E402
from zentinelle_crewai.task import (  # noqa: E402
    GovernedTask,
    TaskApprovalRequired,
    create_governed_task,
)
from zentinelle_crewai.tools import (  # noqa: E402
    GovernedTool,
    ToolApprovalRequired,
    ToolPolicyViolation,
    governed_tool,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Return a mock ZentinelleClient with all governance methods stubbed."""
    client = MagicMock()
    client.emit = MagicMock()
    client.evaluate = MagicMock(
        return_value=_EvaluateResult(allowed=True, reason="ok", policies=[])
    )
    client.register = MagicMock(
        return_value=MagicMock(agent_id="test-agent", session_id="sess-001")
    )
    client.shutdown = MagicMock()
    client.track_usage = MagicMock()
    return client


# =========================================================================
# Callback handler tests
# =========================================================================


class TestZentinelleCrewCallback:
    """Tests for ZentinelleCrewCallback event emission."""

    def test_init_stores_settings(self, mock_client):
        cb = ZentinelleCrewCallback(
            mock_client,
            track_prompts=True,
            track_outputs=False,
            max_output_length=200,
        )
        assert cb._track_prompts is True
        assert cb._track_outputs is False
        assert cb._max_output_length == 200

    # -- Task events -------------------------------------------------------

    def test_on_task_start_emits_event(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)
        task = MagicMock(description="Summarize document")

        cb.on_task_start(task)

        mock_client.emit.assert_called_once()
        kwargs = mock_client.emit.call_args[1]
        assert kwargs["category"] == "task_execution"
        assert kwargs["action"] == "task_start"
        assert kwargs["success"] is True
        assert kwargs["metadata"]["description"] == "Summarize document"

    def test_on_task_end_emits_event_with_output(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client, track_outputs=True)
        task = MagicMock()

        cb.on_task_start(task)
        mock_client.emit.reset_mock()

        cb.on_task_end(task, output="The summary is...")

        mock_client.emit.assert_called_once()
        kwargs = mock_client.emit.call_args[1]
        assert kwargs["action"] == "task_end"
        assert kwargs["metadata"]["output_preview"] == "The summary is..."
        assert kwargs["metadata"]["output_length"] == len("The summary is...")

    def test_on_task_end_omits_output_when_tracking_disabled(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client, track_outputs=False)
        task = MagicMock()

        cb.on_task_start(task)
        mock_client.emit.reset_mock()

        cb.on_task_end(task, output="secret data")

        kwargs = mock_client.emit.call_args[1]
        assert "output_preview" not in kwargs["metadata"]

    def test_on_task_end_truncates_long_output(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client, max_output_length=10)
        task = MagicMock()

        cb.on_task_start(task)
        mock_client.emit.reset_mock()

        cb.on_task_end(task, output="a" * 100)

        kwargs = mock_client.emit.call_args[1]
        assert len(kwargs["metadata"]["output_preview"]) == 10

    def test_on_task_end_records_duration(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)
        task = MagicMock()

        cb.on_task_start(task)
        mock_client.emit.reset_mock()

        cb.on_task_end(task, output="done")

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["metadata"]["duration_ms"] is not None
        assert kwargs["metadata"]["duration_ms"] >= 0

    def test_on_task_error_emits_failure(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)
        task = MagicMock()

        cb.on_task_start(task)
        mock_client.emit.reset_mock()

        cb.on_task_error(task, ValueError("bad input"))

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["action"] == "task_error"
        assert kwargs["success"] is False
        assert kwargs["metadata"]["error"] == "bad input"
        assert kwargs["metadata"]["error_type"] == "ValueError"

    # -- Agent events ------------------------------------------------------

    def test_on_agent_start_emits_event(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)
        agent = MagicMock(role="Researcher")
        task = MagicMock(description="Find papers")

        cb.on_agent_start(agent, task)

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["action"] == "agent_start"
        assert kwargs["metadata"]["role"] == "Researcher"

    def test_on_agent_end_emits_event_with_duration(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)
        agent = MagicMock(role="Writer")

        cb.on_agent_start(agent, MagicMock())
        mock_client.emit.reset_mock()

        cb.on_agent_end(agent, output="article draft")

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["action"] == "agent_end"
        assert kwargs["metadata"]["role"] == "Writer"
        assert kwargs["metadata"]["duration_ms"] is not None

    # -- Tool events -------------------------------------------------------

    def test_on_tool_start_emits_event(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)

        cb.on_tool_start("web_search", "query")

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["category"] == "tool_call"
        assert kwargs["metadata"]["tool"] == "web_search"

    def test_on_tool_start_tracks_input_when_enabled(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client, track_prompts=True)

        cb.on_tool_start("calculator", "2+2")

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["metadata"]["input_preview"] == "2+2"

    def test_on_tool_start_omits_input_when_disabled(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client, track_prompts=False)

        cb.on_tool_start("calculator", "2+2")

        kwargs = mock_client.emit.call_args[1]
        assert "input_preview" not in kwargs["metadata"]

    def test_on_tool_end_emits_event(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)

        cb.on_tool_end("calculator", "4")

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["category"] == "tool_call"
        assert kwargs["success"] is True

    def test_on_tool_error_emits_failure(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)

        cb.on_tool_error("api_call", RuntimeError("timeout"))

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["success"] is False
        assert kwargs["metadata"]["error_type"] == "RuntimeError"

    # -- LLM events --------------------------------------------------------

    def test_on_llm_start_emits_event(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)

        cb.on_llm_start("gpt-4o", ["Hello, world"])

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["category"] == "model_request"
        assert kwargs["metadata"]["model"] == "gpt-4o"
        assert kwargs["metadata"]["prompt_count"] == 1

    def test_on_llm_start_tracks_char_count_when_prompts_enabled(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client, track_prompts=True)

        cb.on_llm_start("claude-3-5-sonnet", ["Hi", "Hello"])

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["metadata"]["total_prompt_chars"] == 7  # 2 + 5

    def test_on_llm_end_tracks_usage(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)

        cb.on_llm_end(
            model="gpt-4o",
            response="generated text",
            input_tokens=100,
            output_tokens=50,
            cost=0.005,
        )

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["category"] == "model_request"
        assert kwargs["success"] is True
        usage = kwargs["model_usage"]
        assert usage.model == "gpt-4o"
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

    def test_on_llm_end_without_tokens_skips_usage(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)

        cb.on_llm_end(model="gpt-4o", response="text")

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["model_usage"] is None

    def test_on_llm_error_emits_failure(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)

        cb.on_llm_error("gpt-4o", RuntimeError("rate limited"))

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["success"] is False
        assert kwargs["metadata"]["error_type"] == "RuntimeError"

    # -- Chain events ------------------------------------------------------

    def test_on_chain_start_emits_event(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)

        cb.on_chain_start("research_pipeline")

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["category"] == "task_execution"
        assert kwargs["metadata"]["chain"] == "research_pipeline"

    def test_on_chain_end_emits_event(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)

        cb.on_chain_end("research_pipeline", output="results")

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["metadata"]["chain"] == "research_pipeline"

    # -- Duration helper ---------------------------------------------------

    def test_get_duration_ms_returns_none_for_missing_start(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)
        assert cb._get_duration_ms(None) is None

    def test_get_duration_ms_returns_int(self, mock_client):
        cb = ZentinelleCrewCallback(mock_client)
        result = cb._get_duration_ms(time.time() - 0.5)
        assert isinstance(result, int)
        assert result >= 400  # at least ~500ms, allowing some slack


# =========================================================================
# GovernedAgent tests
# =========================================================================


class TestGovernedAgent:
    """Tests for GovernedAgent policy checks."""

    def test_init_stores_governance_fields(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze data",
            backstory="Expert analyst",
            allowed_tools=["calculator"],
            max_tokens_per_task=1000,
            require_approval_for=["file_writer"],
            risk_level="high",
        )
        assert agent._allowed_tools == ["calculator"]
        assert agent._max_tokens_per_task == 1000
        assert agent._require_approval_for == ["file_writer"]
        assert agent._risk_level == "high"
        assert agent.zentinelle_client is mock_client

    def test_can_use_tool_allowed(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
            allowed_tools=["calculator", "web_search"],
        )

        result = agent.can_use_tool("calculator")

        assert result.allowed is True
        mock_client.evaluate.assert_called_once()
        ctx = mock_client.evaluate.call_args[1]["context"]
        assert ctx["tool"] == "calculator"
        assert ctx["agent_role"] == "Analyst"

    def test_can_use_tool_blocked_by_allowlist(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
            allowed_tools=["calculator"],
        )

        result = agent.can_use_tool("file_writer")

        assert result.allowed is False
        assert "not in agent's allowed tools" in result.reason
        mock_client.evaluate.assert_not_called()

    def test_can_use_tool_no_allowlist_checks_policy(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
        )

        agent.can_use_tool("anything")

        mock_client.evaluate.assert_called_once()

    def test_can_use_tool_requires_approval(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
            require_approval_for=["file_writer"],
        )

        agent.can_use_tool("file_writer")

        ctx = mock_client.evaluate.call_args[1]["context"]
        assert ctx["requires_approval"] is True

    def test_check_model_request_allowed(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
        )

        result = agent.check_model_request("gpt-4o", estimated_tokens=500)

        assert result.allowed is True
        ctx = mock_client.evaluate.call_args[1]["context"]
        assert ctx["model"] == "gpt-4o"

    def test_check_model_request_blocked_by_token_limit(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
            max_tokens_per_task=1000,
        )
        agent._task_token_count = 800

        result = agent.check_model_request("gpt-4o", estimated_tokens=300)

        assert result.allowed is False
        assert "Token limit exceeded" in result.reason
        mock_client.evaluate.assert_not_called()

    def test_record_token_usage(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
        )

        agent.record_token_usage(150)
        agent.record_token_usage(100)

        assert agent._task_token_count == 250
        assert mock_client.emit.call_count == 2
        second_call = mock_client.emit.call_args[1]
        assert second_call["metadata"]["task_total"] == 250

    def test_reset_task_tokens(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
        )
        agent._task_token_count = 500

        agent.reset_task_tokens()

        assert agent._task_token_count == 0


# =========================================================================
# GovernedAgentExecutor tests
# =========================================================================


class TestGovernedAgentExecutor:
    """Tests for GovernedAgentExecutor pre/post execution hooks."""

    def test_pre_execute_resets_tokens_and_evaluates(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
        )
        agent._task_token_count = 999
        executor = GovernedAgentExecutor(agent)

        result = executor.pre_execute("Analyze the dataset")

        assert agent._task_token_count == 0
        assert result.allowed is True
        mock_client.evaluate.assert_called_once()
        ctx = mock_client.evaluate.call_args[1]["context"]
        assert ctx["task_description"] == "Analyze the dataset"

    def test_pre_execute_truncates_long_descriptions(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
        )
        executor = GovernedAgentExecutor(agent)

        executor.pre_execute("x" * 1000)

        ctx = mock_client.evaluate.call_args[1]["context"]
        assert len(ctx["task_description"]) == 500

    def test_post_execute_emits_completion(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
        )
        agent._task_token_count = 200
        executor = GovernedAgentExecutor(agent)

        executor.post_execute(success=True, output="results here")

        mock_client.emit.assert_called_once()
        kwargs = mock_client.emit.call_args[1]
        assert kwargs["action"] == "agent_task_complete"
        assert kwargs["success"] is True
        assert kwargs["metadata"]["total_tokens"] == 200
        assert kwargs["metadata"]["output_length"] == len("results here")

    def test_post_execute_no_output(self, mock_client):
        agent = GovernedAgent(
            client=mock_client,
            role="Analyst",
            goal="Analyze",
            backstory="...",
        )
        executor = GovernedAgentExecutor(agent)

        executor.post_execute(success=False)

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["success"] is False
        assert kwargs["metadata"]["output_length"] == 0


# =========================================================================
# GovernedCrew tests
# =========================================================================


class TestGovernedCrew:
    """Tests for GovernedCrew governance at the crew level."""

    def _make_agents(self, mock_client, count=2):
        return [
            GovernedAgent(
                client=mock_client,
                role=f"Agent-{i}",
                goal="goal",
                backstory="...",
            )
            for i in range(count)
        ]

    def _make_tasks(self, count=1):
        # Use the crewai stub Task directly
        import crewai
        return [
            crewai.Task(description=f"Task-{i}", expected_output="output")
            for i in range(count)
        ]

    def test_kickoff_registers_session(self, mock_client):
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
            session_metadata={"user_id": "user-1"},
        )

        crew.kickoff()

        mock_client.register.assert_called_once()
        reg_kwargs = mock_client.register.call_args[1]
        assert reg_kwargs["user_id"] == "user-1"
        assert reg_kwargs["metadata"]["crew_size"] == 2

    def test_kickoff_checks_policy(self, mock_client):
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
        )

        crew.kickoff()

        mock_client.evaluate.assert_called_once()
        args = mock_client.evaluate.call_args
        assert args[0][0] == "crew_kickoff"

    def test_kickoff_blocked_raises_policy_violation(self, mock_client):
        mock_client.evaluate.return_value = _EvaluateResult(
            allowed=False,
            reason="cost budget exceeded",
            policies=[],
        )
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
        )

        with pytest.raises(PolicyViolationError, match="cost budget exceeded"):
            crew.kickoff()

        # Should emit a blocked event
        emit_calls = [
            c for c in mock_client.emit.call_args_list
            if c[1].get("action") == "crew_kickoff_blocked"
        ]
        assert len(emit_calls) == 1

    def test_kickoff_records_completion_on_success(self, mock_client):
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
        )

        crew.kickoff()

        completion_calls = [
            c for c in mock_client.emit.call_args_list
            if c[1].get("action") == "crew_complete"
        ]
        assert len(completion_calls) == 1
        assert completion_calls[0][1]["success"] is True

    def test_kickoff_records_completion_on_failure(self, mock_client):
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
        )

        # Make super().kickoff() raise
        with patch.object(
            type(crew).__bases__[0], "kickoff", side_effect=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError, match="boom"):
                crew.kickoff()

        completion_calls = [
            c for c in mock_client.emit.call_args_list
            if c[1].get("action") == "crew_complete"
        ]
        assert len(completion_calls) == 1
        assert completion_calls[0][1]["success"] is False
        assert completion_calls[0][1]["metadata"]["error"] == "boom"

    def test_record_cost_within_limits(self, mock_client):
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
            max_total_cost=1.00,
            max_total_tokens=10000,
        )

        result = crew.record_cost(cost=0.25, tokens=500, model="gpt-4o")

        assert result.allowed is True
        assert crew._total_cost == 0.25
        assert crew._total_tokens == 500

    def test_record_cost_exceeds_cost_limit(self, mock_client):
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
            max_total_cost=0.50,
        )

        crew.record_cost(cost=0.30, tokens=100, model="gpt-4o")
        result = crew.record_cost(cost=0.30, tokens=100, model="gpt-4o")

        assert result.allowed is False
        assert "Cost limit exceeded" in result.reason

    def test_record_cost_exceeds_token_limit(self, mock_client):
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
            max_total_tokens=500,
        )

        crew.record_cost(cost=0.01, tokens=300, model="gpt-4o")
        result = crew.record_cost(cost=0.01, tokens=300, model="gpt-4o")

        assert result.allowed is False
        assert "Token limit exceeded" in result.reason

    def test_record_cost_emits_usage(self, mock_client):
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
        )

        crew.record_cost(cost=0.10, tokens=200, model="gpt-4o")

        mock_client.emit.assert_called_once()
        kwargs = mock_client.emit.call_args[1]
        assert kwargs["category"] == "model_request"
        usage = kwargs["model_usage"]
        assert usage.model == "gpt-4o"
        assert usage.cost == 0.10

    def test_get_usage_summary(self, mock_client):
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
            max_total_cost=5.00,
            max_total_tokens=10000,
        )
        crew._start_time = time.time() - 10
        crew._session_id = "sess-001"
        crew._total_cost = 1.50
        crew._total_tokens = 3000

        summary = crew.get_usage_summary()

        assert summary["session_id"] == "sess-001"
        assert summary["total_cost"] == 1.50
        assert summary["total_tokens"] == 3000
        assert summary["cost_remaining"] == 3.50
        assert summary["tokens_remaining"] == 7000
        assert summary["duration_seconds"] >= 9

    def test_kickoff_with_cost_and_token_limits_in_context(self, mock_client):
        agents = self._make_agents(mock_client)
        tasks = self._make_tasks()

        crew = GovernedCrew(
            client=mock_client,
            agents=agents,
            tasks=tasks,
            max_total_cost=2.00,
            max_total_tokens=5000,
        )

        crew.kickoff()

        ctx = mock_client.evaluate.call_args[1]["context"]
        assert ctx["max_cost"] == 2.00
        assert ctx["max_tokens"] == 5000


# =========================================================================
# GovernedTask tests
# =========================================================================


class TestGovernedTask:
    """Tests for GovernedTask policy checks and output validation."""

    def test_check_execution_policy_allowed(self, mock_client):
        task = GovernedTask(
            client=mock_client,
            description="Summarize the report",
            expected_output="A one-paragraph summary",
            risk_level="low",
        )

        result = task.check_execution_policy()

        assert result.allowed is True
        ctx = mock_client.evaluate.call_args[1]["context"]
        assert ctx["risk_level"] == "low"

    def test_check_execution_policy_blocked(self, mock_client):
        mock_client.evaluate.return_value = _EvaluateResult(
            allowed=False,
            reason="sensitive data detected",
            policies=[],
        )
        task = GovernedTask(
            client=mock_client,
            description="Export user PII",
            expected_output="CSV file",
            risk_level="critical",
        )

        result = task.check_execution_policy()

        assert result.allowed is False

    def test_check_execution_policy_requires_approval(self, mock_client):
        mock_client.evaluate.return_value = _EvaluateResult(
            allowed=True,
            reason="needs human review",
            requires_approval=True,
            approval_workflow_id="wf-123",
            policies=[],
        )
        task = GovernedTask(
            client=mock_client,
            description="Delete production data",
            expected_output="Confirmation",
            require_approval=True,
        )

        with pytest.raises(TaskApprovalRequired) as exc_info:
            task.check_execution_policy()

        assert exc_info.value.workflow_id == "wf-123"

    def test_check_execution_policy_passes_extra_context(self, mock_client):
        task = GovernedTask(
            client=mock_client,
            description="Analyze data",
            expected_output="Report",
            sensitive_fields=["ssn", "email"],
        )

        task.check_execution_policy(context={"department": "finance"})

        ctx = mock_client.evaluate.call_args[1]["context"]
        assert ctx["department"] == "finance"
        assert ctx["sensitive_fields"] == ["ssn", "email"]

    def test_validate_output_allowed(self, mock_client):
        task = GovernedTask(
            client=mock_client,
            description="Summarize",
            expected_output="Summary",
        )

        result = task.validate_output("This is a clean summary.")

        assert result.allowed is True

    def test_validate_output_exceeds_max_length(self, mock_client):
        task = GovernedTask(
            client=mock_client,
            description="Summarize",
            expected_output="Summary",
            max_output_length=10,
        )

        result = task.validate_output("x" * 100)

        assert result.allowed is False
        assert "exceeds max length" in result.reason
        mock_client.evaluate.assert_not_called()

    def test_validate_output_custom_validator_passes(self, mock_client):
        def no_profanity(output):
            return "badword" not in output

        task = GovernedTask(
            client=mock_client,
            description="Write article",
            expected_output="Article",
            output_validators=[no_profanity],
        )

        result = task.validate_output("Clean and professional article.")

        assert result.allowed is True

    def test_validate_output_custom_validator_fails(self, mock_client):
        def no_profanity(output):
            return "badword" not in output

        task = GovernedTask(
            client=mock_client,
            description="Write article",
            expected_output="Article",
            output_validators=[no_profanity],
        )

        result = task.validate_output("This contains badword content.")

        assert result.allowed is False
        assert "no_profanity" in result.reason
        mock_client.evaluate.assert_not_called()

    def test_validate_output_validator_exception(self, mock_client):
        def broken_validator(output):
            raise RuntimeError("validator crashed")

        task = GovernedTask(
            client=mock_client,
            description="Write article",
            expected_output="Article",
            output_validators=[broken_validator],
        )

        result = task.validate_output("some output")

        assert result.allowed is False
        assert "Validator error" in result.reason

    def test_record_completion(self, mock_client):
        task = GovernedTask(
            client=mock_client,
            description="Summarize the report on Q4 earnings",
            expected_output="Summary",
            risk_level="medium",
        )

        task.record_completion(
            success=True,
            output="Q4 earnings were strong.",
            duration_ms=1500,
        )

        kwargs = mock_client.emit.call_args[1]
        assert kwargs["action"] == "task_complete"
        assert kwargs["success"] is True
        assert kwargs["metadata"]["duration_ms"] == 1500
        assert kwargs["metadata"]["risk_level"] == "medium"


class TestCreateGovernedTask:
    """Tests for the create_governed_task factory function."""

    def test_infers_high_risk_from_keywords(self, mock_client):
        task = create_governed_task(
            client=mock_client,
            description="Delete all production records",
            expected_output="Confirmation",
        )
        assert task._risk_level == "high"

    def test_infers_medium_risk_from_keywords(self, mock_client):
        task = create_governed_task(
            client=mock_client,
            description="Update the configuration file",
            expected_output="Updated config",
        )
        assert task._risk_level == "medium"

    def test_infers_low_risk_by_default(self, mock_client):
        task = create_governed_task(
            client=mock_client,
            description="Read the status page",
            expected_output="Status info",
        )
        assert task._risk_level == "low"

    def test_explicit_risk_level_overrides_inference(self, mock_client):
        task = create_governed_task(
            client=mock_client,
            description="Delete everything",  # would infer "high"
            expected_output="Done",
            risk_level="low",
        )
        assert task._risk_level == "low"


# =========================================================================
# GovernedTool tests
# =========================================================================


class TestGovernedTool:
    """Tests for GovernedTool policy enforcement on tool calls."""

    def _make_tool(self, mock_client, func=None, **kwargs):
        if func is None:
            func = lambda **kw: "result"
        defaults = dict(
            client=mock_client,
            name="test_tool",
            description="A test tool",
            func=func,
        )
        defaults.update(kwargs)
        return GovernedTool(**defaults)

    def test_run_allowed_executes_function(self, mock_client):
        called_with = {}

        def my_func(**kwargs):
            called_with.update(kwargs)
            return "ok"

        tool = self._make_tool(mock_client, func=my_func)

        result = tool._run(x="hello")

        assert result == "ok"
        assert called_with == {"x": "hello"}

    def test_run_emits_success_event(self, mock_client):
        tool = self._make_tool(mock_client)

        tool._run()

        # evaluate + emit for success
        success_calls = [
            c for c in mock_client.emit.call_args_list
            if c[1].get("success") is True
        ]
        assert len(success_calls) == 1
        assert success_calls[0][1]["category"] == "tool_call"
        assert success_calls[0][1]["metadata"]["call_count"] == 1

    def test_run_increments_call_count(self, mock_client):
        tool = self._make_tool(mock_client)

        tool._run()
        tool._run()
        tool._run()

        assert tool._call_count == 3

    def test_run_blocked_by_policy_raises(self, mock_client):
        mock_client.evaluate.return_value = _EvaluateResult(
            allowed=False,
            reason="tool not permitted",
            policies=[],
        )
        tool = self._make_tool(mock_client)

        with pytest.raises(ToolPolicyViolation, match="tool not permitted"):
            tool._run()

        # Should emit blocked event
        mock_client.emit.assert_called_once()
        kwargs = mock_client.emit.call_args[1]
        assert kwargs["success"] is False
        assert kwargs["metadata"]["blocked_reason"] == "tool not permitted"

    def test_run_blocked_does_not_increment_count(self, mock_client):
        mock_client.evaluate.return_value = _EvaluateResult(
            allowed=False,
            reason="blocked",
            policies=[],
        )
        tool = self._make_tool(mock_client)

        with pytest.raises(ToolPolicyViolation):
            tool._run()

        assert tool._call_count == 0

    def test_run_requires_approval_raises(self, mock_client):
        mock_client.evaluate.return_value = _EvaluateResult(
            allowed=True,
            reason="needs approval",
            requires_approval=True,
            approval_workflow_id="wf-456",
            policies=[],
        )
        tool = self._make_tool(mock_client)

        with pytest.raises(ToolApprovalRequired) as exc_info:
            tool._run()

        assert exc_info.value.workflow_id == "wf-456"

    def test_run_exceeds_call_limit(self, mock_client):
        tool = self._make_tool(mock_client, max_calls_per_session=2)

        tool._run()
        tool._run()

        with pytest.raises(ToolPolicyViolation, match="call limit exceeded"):
            tool._run()

    def test_run_function_raises_emits_error(self, mock_client):
        def failing_func(**kwargs):
            raise ValueError("something broke")

        tool = self._make_tool(mock_client, func=failing_func)

        with pytest.raises(ValueError, match="something broke"):
            tool._run()

        error_calls = [
            c for c in mock_client.emit.call_args_list
            if c[1].get("success") is False
        ]
        assert len(error_calls) == 1
        assert error_calls[0][1]["metadata"]["error"] == "something broke"

    def test_reset_call_count(self, mock_client):
        tool = self._make_tool(mock_client)
        tool._call_count = 5

        tool.reset_call_count()

        assert tool._call_count == 0

    def test_cost_per_call_recorded(self, mock_client):
        tool = self._make_tool(mock_client, cost_per_call=0.05)

        tool._run()

        success_calls = [
            c for c in mock_client.emit.call_args_list
            if c[1].get("success") is True
        ]
        assert success_calls[0][1]["metadata"]["cost"] == 0.05


class TestGovernedToolDecorator:
    """Tests for the @governed_tool decorator."""

    def test_decorator_creates_governed_tool(self, mock_client):
        @governed_tool(
            client=mock_client,
            name="my_calculator",
            description="Does math",
            risk_level="low",
        )
        def calculate(expression: str = "") -> str:
            return "42"

        assert isinstance(calculate, GovernedTool)
        assert calculate.name == "my_calculator"
        assert calculate.risk_level == "low"

    def test_decorator_infers_name_from_function(self, mock_client):
        @governed_tool(client=mock_client)
        def search_web(query: str = "") -> str:
            """Search the web for information."""
            return "results"

        assert search_web.name == "search_web"
        assert search_web.description == "Search the web for information."

    def test_decorator_tool_executes(self, mock_client):
        @governed_tool(client=mock_client, name="adder")
        def add(a: int = 0, b: int = 0) -> int:
            return a + b

        result = add._run(a=2, b=3)

        assert result == 5


# =========================================================================
# Exception classes
# =========================================================================


class TestExceptions:
    """Tests for custom exception types."""

    def test_policy_violation_error_message(self):
        err = PolicyViolationError("budget exceeded")
        assert str(err) == "budget exceeded"

    def test_tool_policy_violation_message(self):
        err = ToolPolicyViolation("tool blocked")
        assert str(err) == "tool blocked"

    def test_tool_approval_required_attributes(self):
        err = ToolApprovalRequired(
            tool_name="file_writer",
            workflow_id="wf-789",
            reason="high-risk operation",
        )
        assert err.tool_name == "file_writer"
        assert err.workflow_id == "wf-789"
        assert err.reason == "high-risk operation"
        assert "file_writer" in str(err)

    def test_task_approval_required_attributes(self):
        err = TaskApprovalRequired(
            task_name="Delete records",
            workflow_id="wf-101",
            reason="destructive operation",
        )
        assert err.task_name == "Delete records"
        assert err.workflow_id == "wf-101"
        assert "destructive operation" in str(err)
