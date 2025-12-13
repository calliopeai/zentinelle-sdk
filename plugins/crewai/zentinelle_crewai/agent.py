"""
Governed agent implementation for CrewAI.
"""

from typing import Any, Optional

from crewai import Agent
from zentinelle import ZentinelleClient
from zentinelle.types import EvaluateResult


class GovernedAgent(Agent):
    """
    A CrewAI Agent with Zentinelle governance controls.

    Enforces policies on:
    - Model selection and usage
    - Tool execution
    - Token limits per task
    - Cost constraints

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        agent = GovernedAgent(
            client=client,
            role="Data Analyst",
            goal="Analyze data accurately",
            backstory="Expert in data analysis",
            allowed_tools=["calculator", "file_reader"],
            max_tokens_per_task=4000,
            require_approval_for=["file_writer", "api_caller"]
        )
    """

    def __init__(
        self,
        client: ZentinelleClient,
        role: str,
        goal: str,
        backstory: str,
        allowed_tools: Optional[list[str]] = None,
        max_tokens_per_task: Optional[int] = None,
        require_approval_for: Optional[list[str]] = None,
        risk_level: str = "medium",
        **kwargs: Any,
    ):
        """
        Initialize a governed agent.

        Args:
            client: Zentinelle client instance
            role: Agent's role in the crew
            goal: Agent's goal
            backstory: Agent's backstory for context
            allowed_tools: List of tools this agent can use (None = all allowed by policy)
            max_tokens_per_task: Maximum tokens per task execution
            require_approval_for: Tools requiring human approval
            risk_level: Agent risk level (low, medium, high, critical)
            **kwargs: Additional arguments passed to CrewAI Agent
        """
        super().__init__(role=role, goal=goal, backstory=backstory, **kwargs)
        self._client = client
        self._allowed_tools = allowed_tools
        self._max_tokens_per_task = max_tokens_per_task
        self._require_approval_for = require_approval_for or []
        self._risk_level = risk_level
        self._task_token_count = 0

    @property
    def zentinelle_client(self) -> ZentinelleClient:
        """Get the Zentinelle client."""
        return self._client

    def can_use_tool(self, tool_name: str) -> EvaluateResult:
        """
        Check if the agent can use a specific tool.

        Args:
            tool_name: Name of the tool to check

        Returns:
            EvaluateResult with policy decision
        """
        # Check local restrictions first
        if self._allowed_tools is not None and tool_name not in self._allowed_tools:
            return EvaluateResult(
                allowed=False,
                reason=f"Tool '{tool_name}' not in agent's allowed tools list",
                policies=[],
            )

        # Check if approval required
        if tool_name in self._require_approval_for:
            result = self._client.evaluate(
                "tool_call",
                context={
                    "tool": tool_name,
                    "agent_role": self.role,
                    "requires_approval": True,
                    "risk_level": self._risk_level,
                },
            )
            return result

        # Check Zentinelle policy
        return self._client.evaluate(
            "tool_call",
            context={
                "tool": tool_name,
                "agent_role": self.role,
                "risk_level": self._risk_level,
            },
        )

    def check_model_request(
        self, model: str, estimated_tokens: Optional[int] = None
    ) -> EvaluateResult:
        """
        Check if a model request is allowed.

        Args:
            model: Model identifier
            estimated_tokens: Estimated token count (optional)

        Returns:
            EvaluateResult with policy decision
        """
        # Check token limits
        if self._max_tokens_per_task and estimated_tokens:
            if self._task_token_count + estimated_tokens > self._max_tokens_per_task:
                return EvaluateResult(
                    allowed=False,
                    reason=f"Token limit exceeded: {self._task_token_count + estimated_tokens} > {self._max_tokens_per_task}",
                    policies=[],
                )

        return self._client.evaluate(
            "model_request",
            context={
                "model": model,
                "agent_role": self.role,
                "estimated_tokens": estimated_tokens,
                "current_task_tokens": self._task_token_count,
                "risk_level": self._risk_level,
            },
        )

    def record_token_usage(self, tokens: int) -> None:
        """
        Record token usage for the current task.

        Args:
            tokens: Number of tokens used
        """
        self._task_token_count += tokens
        self._client.emit(
            category="model_request",
            action="token_usage",
            success=True,
            metadata={
                "tokens": tokens,
                "task_total": self._task_token_count,
                "agent_role": self.role,
            },
        )

    def reset_task_tokens(self) -> None:
        """Reset the task token counter (call when starting a new task)."""
        self._task_token_count = 0


class GovernedAgentExecutor:
    """
    Executor wrapper that enforces governance on agent execution.

    Provides hooks into agent execution for:
    - Pre-execution policy checks
    - Tool call interception
    - Usage tracking
    - Cost monitoring
    """

    def __init__(self, agent: GovernedAgent):
        """
        Initialize the executor.

        Args:
            agent: The governed agent to execute
        """
        self._agent = agent

    def pre_execute(self, task_description: str) -> EvaluateResult:
        """
        Run pre-execution checks.

        Args:
            task_description: Description of the task

        Returns:
            EvaluateResult with policy decision
        """
        self._agent.reset_task_tokens()

        return self._agent.zentinelle_client.evaluate(
            "task_start",
            context={
                "agent_role": self._agent.role,
                "task_description": task_description[:500],  # Truncate for safety
                "risk_level": self._agent._risk_level,
            },
        )

    def post_execute(self, success: bool, output: Optional[str] = None) -> None:
        """
        Record post-execution metrics.

        Args:
            success: Whether the task succeeded
            output: Task output (optional, truncated)
        """
        self._agent.zentinelle_client.emit(
            category="task_execution",
            action="agent_task_complete",
            success=success,
            metadata={
                "agent_role": self._agent.role,
                "total_tokens": self._agent._task_token_count,
                "output_length": len(output) if output else 0,
            },
        )
