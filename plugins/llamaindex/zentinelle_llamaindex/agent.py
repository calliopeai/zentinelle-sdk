"""
Governed ReAct agent for LlamaIndex.
"""

import time
from typing import Any, List, Optional, Sequence

from llama_index.core.agent import ReActAgent
from llama_index.core.agent.types import Task
from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.llms import LLM
from llama_index.core.tools import BaseTool
from zentinelle import ZentinelleClient
from zentinelle.types import EvaluateResult, ModelUsage


class AgentActionBlockedError(Exception):
    """Raised when an agent action is blocked by policy."""

    def __init__(self, action: str, reason: str, result: EvaluateResult):
        self.action = action
        self.reason = reason
        self.result = result
        super().__init__(f"Agent action '{action}' blocked: {reason}")


class GovernedReActAgent(ReActAgent):
    """
    A LlamaIndex ReAct agent with Zentinelle governance.

    Provides governance for agent actions:
    - Tool call policy enforcement
    - Iteration limits
    - Cost controls
    - Human-in-the-loop for risky actions

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        tools = [search_tool, calculator_tool]

        agent = GovernedReActAgent.from_governed(
            client=client,
            tools=tools,
            llm=llm,
            max_iterations=10,
            max_cost=1.00,
            require_approval_for=["dangerous_tool"]
        )

        response = agent.chat("Calculate the revenue growth")
    """

    def __init__(
        self,
        client: ZentinelleClient,
        tools: Sequence[BaseTool],
        llm: LLM,
        max_iterations: int = 10,
        max_cost: Optional[float] = None,
        require_approval_for: Optional[list[str]] = None,
        user_id: Optional[str] = None,
        **kwargs: Any,
    ):
        """
        Initialize a governed ReAct agent.

        Args:
            client: Zentinelle client instance
            tools: Tools available to the agent
            llm: Language model to use
            max_iterations: Maximum reasoning iterations
            max_cost: Maximum cost in dollars
            require_approval_for: Tools requiring human approval
            user_id: User ID for tracking
            **kwargs: Additional arguments passed to ReActAgent
        """
        super().__init__(tools=tools, llm=llm, max_iterations=max_iterations, **kwargs)
        self._client = client
        self._max_cost = max_cost
        self._require_approval_for = require_approval_for or []
        self._user_id = user_id

        self._iteration_count = 0
        self._total_cost = 0.0
        self._tool_calls: list[dict[str, Any]] = []

    @classmethod
    def from_governed(
        cls,
        client: ZentinelleClient,
        tools: Sequence[BaseTool],
        llm: LLM,
        **kwargs: Any,
    ) -> "GovernedReActAgent":
        """
        Create a governed ReAct agent.

        Args:
            client: Zentinelle client instance
            tools: Tools available to the agent
            llm: Language model to use
            **kwargs: Additional configuration

        Returns:
            Configured GovernedReActAgent instance
        """
        return cls(client=client, tools=tools, llm=llm, **kwargs)

    @property
    def zentinelle_client(self) -> ZentinelleClient:
        """Get the Zentinelle client."""
        return self._client

    def _check_tool_policy(self, tool_name: str, tool_input: Any) -> EvaluateResult:
        """Check if tool call is allowed."""
        # Check if approval required
        requires_approval = tool_name in self._require_approval_for

        context = {
            "tool": tool_name,
            "input_preview": str(tool_input)[:200],
            "requires_approval": requires_approval,
            "iteration_count": self._iteration_count,
            "total_cost": self._total_cost,
            "max_cost": self._max_cost,
            "user_id": self._user_id,
        }

        return self._client.evaluate("agent_tool_call", context=context)

    def _check_iteration_policy(self) -> EvaluateResult:
        """Check if another iteration is allowed."""
        # Check cost limit
        if self._max_cost and self._total_cost >= self._max_cost:
            return EvaluateResult(
                allowed=False,
                reason=f"Cost limit exceeded: ${self._total_cost:.4f} >= ${self._max_cost:.4f}",
                policies=[],
            )

        context = {
            "iteration_count": self._iteration_count,
            "max_iterations": self._max_iterations,
            "total_cost": self._total_cost,
            "max_cost": self._max_cost,
            "tool_calls": len(self._tool_calls),
            "user_id": self._user_id,
        }

        return self._client.evaluate("agent_iteration", context=context)

    def chat(
        self,
        message: str,
        chat_history: Optional[List[ChatMessage]] = None,
        tool_choice: Optional[str] = None,
    ) -> Any:
        """
        Chat with the agent, enforcing governance policies.

        Args:
            message: User message
            chat_history: Previous chat history
            tool_choice: Optional tool to use

        Returns:
            Agent response
        """
        # Register session
        self._client.register(
            user_id=self._user_id,
            metadata={
                "agent_type": "react",
                "tools": [t.metadata.name for t in self._tools],
                "message_preview": message[:200],
            },
        )

        # Reset iteration tracking
        self._iteration_count = 0
        self._tool_calls = []

        start_time = time.time()

        try:
            # Check initial policy
            result = self._check_iteration_policy()
            if not result.allowed:
                raise AgentActionBlockedError("chat_start", result.reason, result)

            # Execute chat
            response = super().chat(
                message=message,
                chat_history=chat_history,
                tool_choice=tool_choice,
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # Record completion
            self._client.emit(
                category="task_execution",
                action="agent_chat_complete",
                success=True,
                metadata={
                    "duration_ms": duration_ms,
                    "iterations": self._iteration_count,
                    "tool_calls": len(self._tool_calls),
                    "total_cost": self._total_cost,
                    "user_id": self._user_id,
                },
            )

            return response

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)

            self._client.emit(
                category="task_execution",
                action="agent_chat_complete",
                success=False,
                metadata={
                    "duration_ms": duration_ms,
                    "iterations": self._iteration_count,
                    "error": str(e)[:500],
                    "user_id": self._user_id,
                },
            )
            raise

    def record_tool_call(
        self,
        tool_name: str,
        tool_input: Any,
        tool_output: Any,
        success: bool,
        duration_ms: int,
    ) -> None:
        """
        Record a tool call (called by governance hooks).

        Args:
            tool_name: Name of the tool
            tool_input: Tool input
            tool_output: Tool output
            success: Whether call succeeded
            duration_ms: Call duration
        """
        self._tool_calls.append(
            {
                "tool": tool_name,
                "success": success,
                "duration_ms": duration_ms,
            }
        )

        self._client.emit(
            category="tool_call",
            action=tool_name,
            success=success,
            metadata={
                "input_preview": str(tool_input)[:200],
                "output_preview": str(tool_output)[:200] if success else None,
                "duration_ms": duration_ms,
                "iteration": self._iteration_count,
                "user_id": self._user_id,
            },
        )

    def record_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: Optional[float] = None,
    ) -> None:
        """
        Record an LLM call.

        Args:
            model: Model used
            input_tokens: Input token count
            output_tokens: Output token count
            cost: Cost in dollars
        """
        self._iteration_count += 1

        if cost:
            self._total_cost += cost

        self._client.emit(
            category="model_request",
            action=f"agent_llm_{model}",
            success=True,
            model_usage=ModelUsage(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
            ),
            metadata={
                "iteration": self._iteration_count,
                "user_id": self._user_id,
            },
        )

    def get_execution_summary(self) -> dict[str, Any]:
        """Get summary of agent execution."""
        return {
            "iterations": self._iteration_count,
            "tool_calls": self._tool_calls,
            "total_cost": self._total_cost,
            "cost_remaining": (self._max_cost - self._total_cost)
            if self._max_cost
            else None,
        }
