"""
Governed crew implementation for CrewAI.
"""

import time
from typing import Any, Optional

from crewai import Crew, Task
from zentinelle import ZentinelleClient
from zentinelle.types import EvaluateResult, ModelUsage

from zentinelle_crewai.agent import GovernedAgent


class GovernedCrew(Crew):
    """
    A CrewAI Crew with Zentinelle governance controls.

    Provides governance at the crew level:
    - Overall mission approval
    - Agent coordination policies
    - Aggregate cost limits
    - Session tracking

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        researcher = GovernedAgent(client=client, role="Researcher", ...)
        writer = GovernedAgent(client=client, role="Writer", ...)

        crew = GovernedCrew(
            client=client,
            agents=[researcher, writer],
            tasks=[research_task, writing_task],
            max_total_cost=1.00,
            require_approval=True,
            verbose=True
        )

        result = crew.kickoff()
    """

    def __init__(
        self,
        client: ZentinelleClient,
        agents: list[GovernedAgent],
        tasks: list[Task],
        max_total_cost: Optional[float] = None,
        max_total_tokens: Optional[int] = None,
        require_approval: bool = False,
        session_metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ):
        """
        Initialize a governed crew.

        Args:
            client: Zentinelle client instance
            agents: List of governed agents in the crew
            tasks: List of tasks for the crew to complete
            max_total_cost: Maximum total cost in dollars
            max_total_tokens: Maximum total tokens across all agents
            require_approval: Whether crew execution requires human approval
            session_metadata: Additional metadata for the session
            **kwargs: Additional arguments passed to CrewAI Crew
        """
        super().__init__(agents=agents, tasks=tasks, **kwargs)
        self._client = client
        self._max_total_cost = max_total_cost
        self._max_total_tokens = max_total_tokens
        self._require_approval = require_approval
        self._session_metadata = session_metadata or {}

        self._total_cost = 0.0
        self._total_tokens = 0
        self._start_time: Optional[float] = None
        self._session_id: Optional[str] = None

    @property
    def zentinelle_client(self) -> ZentinelleClient:
        """Get the Zentinelle client."""
        return self._client

    def kickoff(self, inputs: Optional[dict[str, Any]] = None) -> Any:
        """
        Start the crew's execution with governance checks.

        Args:
            inputs: Input values for the crew

        Returns:
            Crew execution result

        Raises:
            PolicyViolationError: If crew execution is not allowed
        """
        # Register session
        registration = self._client.register(
            user_id=self._session_metadata.get("user_id"),
            metadata={
                "crew_size": len(self.agents),
                "task_count": len(self.tasks),
                **self._session_metadata,
            },
        )
        self._session_id = registration.session_id

        # Check crew execution policy
        result = self._check_kickoff_policy(inputs)
        if not result.allowed:
            self._client.emit(
                category="policy_evaluation",
                action="crew_kickoff_blocked",
                success=False,
                metadata={
                    "reason": result.reason,
                    "session_id": self._session_id,
                },
            )
            raise PolicyViolationError(f"Crew execution blocked: {result.reason}")

        self._start_time = time.time()

        try:
            # Execute crew
            output = super().kickoff(inputs=inputs)

            # Record success
            self._record_completion(success=True, output=output)
            return output

        except Exception as e:
            # Record failure
            self._record_completion(success=False, error=str(e))
            raise

    def _check_kickoff_policy(
        self, inputs: Optional[dict[str, Any]] = None
    ) -> EvaluateResult:
        """Check if crew kickoff is allowed."""
        context = {
            "crew_size": len(self.agents),
            "task_count": len(self.tasks),
            "agent_roles": [a.role for a in self.agents if isinstance(a, GovernedAgent)],
            "require_approval": self._require_approval,
            "inputs": inputs or {},
        }

        if self._max_total_cost:
            context["max_cost"] = self._max_total_cost
        if self._max_total_tokens:
            context["max_tokens"] = self._max_total_tokens

        return self._client.evaluate("crew_kickoff", context=context)

    def _record_completion(
        self,
        success: bool,
        output: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> None:
        """Record crew completion metrics."""
        duration = time.time() - self._start_time if self._start_time else 0

        self._client.emit(
            category="task_execution",
            action="crew_complete",
            success=success,
            metadata={
                "session_id": self._session_id,
                "duration_seconds": duration,
                "total_cost": self._total_cost,
                "total_tokens": self._total_tokens,
                "error": error,
                "output_type": type(output).__name__ if output else None,
            },
        )

    def record_cost(self, cost: float, tokens: int, model: str) -> EvaluateResult:
        """
        Record cost and check limits.

        Args:
            cost: Cost in dollars
            tokens: Number of tokens
            model: Model used

        Returns:
            EvaluateResult indicating if limits are exceeded
        """
        self._total_cost += cost
        self._total_tokens += tokens

        # Check cost limit
        if self._max_total_cost and self._total_cost > self._max_total_cost:
            return EvaluateResult(
                allowed=False,
                reason=f"Cost limit exceeded: ${self._total_cost:.4f} > ${self._max_total_cost:.4f}",
                policies=[],
            )

        # Check token limit
        if self._max_total_tokens and self._total_tokens > self._max_total_tokens:
            return EvaluateResult(
                allowed=False,
                reason=f"Token limit exceeded: {self._total_tokens} > {self._max_total_tokens}",
                policies=[],
            )

        # Track usage
        self._client.emit(
            category="model_request",
            action=f"crew_usage_{model}",
            success=True,
            model_usage=ModelUsage(
                model=model,
                input_tokens=tokens // 2,  # Approximate split
                output_tokens=tokens // 2,
                cost=cost,
            ),
        )

        return EvaluateResult(allowed=True, reason="within_limits", policies=[])

    def get_usage_summary(self) -> dict[str, Any]:
        """
        Get a summary of crew usage.

        Returns:
            Dictionary with usage metrics
        """
        return {
            "session_id": self._session_id,
            "total_cost": self._total_cost,
            "total_tokens": self._total_tokens,
            "duration_seconds": time.time() - self._start_time
            if self._start_time
            else 0,
            "cost_remaining": (self._max_total_cost - self._total_cost)
            if self._max_total_cost
            else None,
            "tokens_remaining": (self._max_total_tokens - self._total_tokens)
            if self._max_total_tokens
            else None,
        }


class PolicyViolationError(Exception):
    """Raised when a policy blocks crew execution."""

    pass
