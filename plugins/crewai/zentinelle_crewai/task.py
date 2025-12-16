"""
Governed task implementation for CrewAI.
"""

from typing import Any, Callable, Optional

from crewai import Task
from zentinelle import ZentinelleClient
from zentinelle.types import EvaluateResult


class TaskApprovalRequired(Exception):
    """Raised when a task requires human approval before execution."""

    def __init__(self, task_name: str, workflow_id: str, reason: str):
        self.task_name = task_name
        self.workflow_id = workflow_id
        self.reason = reason
        super().__init__(f"Task '{task_name}' requires approval: {reason}")


class GovernedTask(Task):
    """
    A CrewAI Task with Zentinelle governance controls.

    Provides task-level governance:
    - Pre-execution policy checks
    - Output validation
    - Human-in-the-loop approval
    - Sensitive data detection

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        task = GovernedTask(
            client=client,
            description="Research competitor pricing",
            expected_output="Pricing comparison table",
            risk_level="high",
            require_approval=True,
            sensitive_fields=["pricing", "revenue"],
            agent=researcher
        )
    """

    def __init__(
        self,
        client: ZentinelleClient,
        description: str,
        expected_output: str,
        risk_level: str = "medium",
        require_approval: bool = False,
        sensitive_fields: Optional[list[str]] = None,
        output_validators: Optional[list[Callable[[str], bool]]] = None,
        max_output_length: Optional[int] = None,
        **kwargs: Any,
    ):
        """
        Initialize a governed task.

        Args:
            client: Zentinelle client instance
            description: Task description
            expected_output: Description of expected output
            risk_level: Task risk level (low, medium, high, critical)
            require_approval: Whether task requires human approval
            sensitive_fields: Fields to check for sensitive data
            output_validators: Functions to validate task output
            max_output_length: Maximum allowed output length
            **kwargs: Additional arguments passed to CrewAI Task
        """
        super().__init__(
            description=description, expected_output=expected_output, **kwargs
        )
        self._client = client
        self._risk_level = risk_level
        self._require_approval = require_approval
        self._sensitive_fields = sensitive_fields or []
        self._output_validators = output_validators or []
        self._max_output_length = max_output_length

    @property
    def zentinelle_client(self) -> ZentinelleClient:
        """Get the Zentinelle client."""
        return self._client

    def check_execution_policy(
        self, context: Optional[dict[str, Any]] = None
    ) -> EvaluateResult:
        """
        Check if task execution is allowed.

        Args:
            context: Additional context for policy evaluation

        Returns:
            EvaluateResult with policy decision
        """
        eval_context = {
            "task_description": self.description[:500],
            "expected_output": self.expected_output[:200],
            "risk_level": self._risk_level,
            "require_approval": self._require_approval,
            "sensitive_fields": self._sensitive_fields,
            **(context or {}),
        }

        result = self._client.evaluate("task_execution", context=eval_context)

        # Check for approval requirement
        if result.requires_approval and self._require_approval:
            raise TaskApprovalRequired(
                task_name=self.description[:50],
                workflow_id=result.approval_workflow_id or "unknown",
                reason=result.reason or "Task requires human approval",
            )

        return result

    def validate_output(self, output: str) -> EvaluateResult:
        """
        Validate task output against policies and validators.

        Args:
            output: Task output to validate

        Returns:
            EvaluateResult with validation result
        """
        # Check output length
        if self._max_output_length and len(output) > self._max_output_length:
            return EvaluateResult(
                allowed=False,
                reason=f"Output exceeds max length: {len(output)} > {self._max_output_length}",
                policies=[],
            )

        # Run custom validators
        for validator in self._output_validators:
            try:
                if not validator(output):
                    return EvaluateResult(
                        allowed=False,
                        reason=f"Output failed validation: {validator.__name__}",
                        policies=[],
                    )
            except Exception as e:
                return EvaluateResult(
                    allowed=False,
                    reason=f"Validator error: {str(e)}",
                    policies=[],
                )

        # Check for sensitive data via Zentinelle
        return self._client.evaluate(
            "output_validation",
            context={
                "output_length": len(output),
                "output_preview": output[:200],
                "sensitive_fields": self._sensitive_fields,
                "task_description": self.description[:200],
            },
        )

    def record_completion(
        self,
        success: bool,
        output: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """
        Record task completion.

        Args:
            success: Whether task succeeded
            output: Task output (truncated for privacy)
            error: Error message if failed
            duration_ms: Execution duration in milliseconds
        """
        self._client.emit(
            category="task_execution",
            action="task_complete",
            success=success,
            metadata={
                "task_description": self.description[:100],
                "risk_level": self._risk_level,
                "output_length": len(output) if output else 0,
                "error": error,
                "duration_ms": duration_ms,
            },
        )


def create_governed_task(
    client: ZentinelleClient,
    description: str,
    expected_output: str,
    **kwargs: Any,
) -> GovernedTask:
    """
    Factory function to create a governed task with sensible defaults.

    Args:
        client: Zentinelle client instance
        description: Task description
        expected_output: Expected output description
        **kwargs: Additional task arguments

    Returns:
        Configured GovernedTask instance
    """
    # Infer risk level from description keywords
    description_lower = description.lower()
    if any(
        word in description_lower
        for word in ["delete", "remove", "critical", "production", "financial"]
    ):
        risk_level = "high"
    elif any(
        word in description_lower for word in ["modify", "update", "change", "external"]
    ):
        risk_level = "medium"
    else:
        risk_level = "low"

    return GovernedTask(
        client=client,
        description=description,
        expected_output=expected_output,
        risk_level=kwargs.pop("risk_level", risk_level),
        **kwargs,
    )
