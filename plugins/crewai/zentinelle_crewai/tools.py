"""
Governed tools for CrewAI agents.
"""

import time
from typing import Any, Callable, Optional, TypeVar

from crewai.tools import BaseTool
from pydantic import Field
from zentinelle import ZentinelleClient
from zentinelle.types import EvaluateResult

T = TypeVar("T")


class GovernedTool(BaseTool):
    """
    A CrewAI tool with Zentinelle governance.

    Wraps tool execution with:
    - Pre-execution policy checks
    - Usage tracking
    - Cost monitoring
    - Human-in-the-loop approval

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        web_search = GovernedTool(
            client=client,
            name="web_search",
            description="Search the web for information",
            func=search_function,
            risk_level="medium",
            require_approval=False
        )

        # Use in agent
        agent = Agent(tools=[web_search], ...)
    """

    client: ZentinelleClient = Field(exclude=True)
    risk_level: str = Field(default="medium")
    require_approval: bool = Field(default=False)
    max_calls_per_session: Optional[int] = Field(default=None)
    cost_per_call: Optional[float] = Field(default=None)

    _call_count: int = 0

    def __init__(
        self,
        client: ZentinelleClient,
        name: str,
        description: str,
        func: Callable[..., Any],
        risk_level: str = "medium",
        require_approval: bool = False,
        max_calls_per_session: Optional[int] = None,
        cost_per_call: Optional[float] = None,
        **kwargs: Any,
    ):
        """
        Initialize a governed tool.

        Args:
            client: Zentinelle client instance
            name: Tool name
            description: Tool description
            func: Function to execute
            risk_level: Tool risk level (low, medium, high, critical)
            require_approval: Whether tool requires human approval
            max_calls_per_session: Maximum calls per session (None = unlimited)
            cost_per_call: Estimated cost per call in dollars
            **kwargs: Additional arguments passed to BaseTool
        """
        super().__init__(
            name=name,
            description=description,
            func=func,
            client=client,
            risk_level=risk_level,
            require_approval=require_approval,
            max_calls_per_session=max_calls_per_session,
            cost_per_call=cost_per_call,
            **kwargs,
        )

    def _check_policy(self, **kwargs: Any) -> EvaluateResult:
        """Check if tool execution is allowed."""
        # Check call limit
        if self.max_calls_per_session and self._call_count >= self.max_calls_per_session:
            return EvaluateResult(
                allowed=False,
                reason=f"Tool call limit exceeded: {self._call_count} >= {self.max_calls_per_session}",
                policies=[],
            )

        context = {
            "tool": self.name,
            "risk_level": self.risk_level,
            "require_approval": self.require_approval,
            "call_count": self._call_count,
            "cost_per_call": self.cost_per_call,
            "args": {k: str(v)[:100] for k, v in kwargs.items()},  # Truncate args
        }

        return self.client.evaluate("tool_call", context=context)

    def _run(self, **kwargs: Any) -> Any:
        """Execute the tool with governance checks."""
        # Check policy
        result = self._check_policy(**kwargs)
        if not result.allowed:
            self.client.emit(
                category="tool_call",
                action=self.name,
                success=False,
                metadata={"blocked_reason": result.reason, "args": str(kwargs)[:200]},
            )
            raise ToolPolicyViolation(f"Tool '{self.name}' blocked: {result.reason}")

        if result.requires_approval:
            raise ToolApprovalRequired(
                tool_name=self.name,
                workflow_id=result.approval_workflow_id or "unknown",
                reason=result.reason or "Tool requires human approval",
            )

        # Execute tool
        start_time = time.time()
        try:
            output = self.func(**kwargs)
            duration_ms = int((time.time() - start_time) * 1000)

            self._call_count += 1

            # Record success
            self.client.emit(
                category="tool_call",
                action=self.name,
                success=True,
                metadata={
                    "duration_ms": duration_ms,
                    "call_count": self._call_count,
                    "cost": self.cost_per_call,
                },
            )

            return output

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)

            # Record failure
            self.client.emit(
                category="tool_call",
                action=self.name,
                success=False,
                metadata={
                    "duration_ms": duration_ms,
                    "error": str(e)[:500],
                    "call_count": self._call_count,
                },
            )
            raise

    def reset_call_count(self) -> None:
        """Reset the call count (call at session start)."""
        self._call_count = 0


def governed_tool(
    client: ZentinelleClient,
    name: Optional[str] = None,
    description: Optional[str] = None,
    risk_level: str = "medium",
    require_approval: bool = False,
    max_calls_per_session: Optional[int] = None,
    cost_per_call: Optional[float] = None,
) -> Callable[[Callable[..., T]], GovernedTool]:
    """
    Decorator to create a governed tool from a function.

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        @governed_tool(
            client=client,
            name="calculator",
            description="Perform mathematical calculations",
            risk_level="low"
        )
        def calculate(expression: str) -> float:
            # WARNING: Use a safe math parser in production, never eval()
            import ast
            return ast.literal_eval(expression)  # Only evaluates literals

        # Use in agent
        agent = Agent(tools=[calculate], ...)
    """

    def decorator(func: Callable[..., T]) -> GovernedTool:
        tool_name = name or func.__name__
        tool_description = description or func.__doc__ or f"Execute {tool_name}"

        return GovernedTool(
            client=client,
            name=tool_name,
            description=tool_description,
            func=func,
            risk_level=risk_level,
            require_approval=require_approval,
            max_calls_per_session=max_calls_per_session,
            cost_per_call=cost_per_call,
        )

    return decorator


class ToolPolicyViolation(Exception):
    """Raised when a tool call is blocked by policy."""

    pass


class ToolApprovalRequired(Exception):
    """Raised when a tool call requires human approval."""

    def __init__(self, tool_name: str, workflow_id: str, reason: str):
        self.tool_name = tool_name
        self.workflow_id = workflow_id
        self.reason = reason
        super().__init__(f"Tool '{tool_name}' requires approval: {reason}")
