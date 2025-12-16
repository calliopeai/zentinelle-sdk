"""
Governed multi-agent orchestration for Microsoft Agent Framework.
"""
import logging
from typing import Any, Dict, List, Optional, Callable, Awaitable, Union
from dataclasses import dataclass, field

from zentinelle import ZentinelleClient, EvaluateResult

from .extension import ZentinelleAgentExtension, GovernanceConfig, PolicyViolationError

logger = logging.getLogger(__name__)


@dataclass
class GovernedAgent:
    """
    Configuration for a governed agent in the orchestration.

    Attributes:
        name: Agent identifier
        allowed_tools: List of tools this agent can use
        allowed_handoff_targets: Agents this agent can hand off to
        max_turns: Maximum conversation turns
        require_approval_for: Actions that require human approval
    """
    name: str
    allowed_tools: List[str] = field(default_factory=list)
    allowed_handoff_targets: List[str] = field(default_factory=list)
    max_turns: int = 50
    require_approval_for: List[str] = field(default_factory=list)

    def can_use_tool(self, tool_name: str) -> bool:
        """Check if agent can use a specific tool."""
        if not self.allowed_tools:
            return True  # No restrictions
        return tool_name in self.allowed_tools

    def can_handoff_to(self, target_agent: str) -> bool:
        """Check if agent can hand off to another agent."""
        if not self.allowed_handoff_targets:
            return True  # No restrictions
        return target_agent in self.allowed_handoff_targets


class ZentinelleOrchestrator:
    """
    Governed multi-agent orchestrator for Microsoft Agent Framework.

    Provides centralized governance for multi-agent workflows:
    - Agent capability restrictions
    - Handoff policy enforcement
    - Turn limits and conversation boundaries
    - Cross-agent telemetry

    Usage:
        from zentinelle_ms_agent import ZentinelleOrchestrator, GovernedAgent

        orchestrator = ZentinelleOrchestrator(
            api_key="sk_agent_...",
            agents=[
                GovernedAgent(
                    name="planner",
                    allowed_tools=["search", "calendar"],
                    allowed_handoff_targets=["executor"],
                ),
                GovernedAgent(
                    name="executor",
                    allowed_tools=["code", "terminal"],
                    allowed_handoff_targets=["planner"],
                    max_turns=20,
                ),
            ],
        )

        # Evaluate handoff
        result = await orchestrator.can_handoff("planner", "executor")

        # Track turns
        await orchestrator.track_turn("planner", message, user_id)
    """

    def __init__(
        self,
        api_key: str,
        agents: List[GovernedAgent],
        endpoint: Optional[str] = None,
        config: Optional[GovernanceConfig] = None,
        max_total_turns: int = 100,
        **client_kwargs,
    ):
        """
        Initialize orchestrator.

        Args:
            api_key: Zentinelle API key
            agents: List of governed agent configurations
            endpoint: Custom Zentinelle endpoint
            config: Governance configuration
            max_total_turns: Maximum turns across all agents
            **client_kwargs: Additional ZentinelleClient args
        """
        self.client = ZentinelleClient(
            api_key=api_key,
            agent_type="ms-agent-framework-orchestrator",
            endpoint=endpoint,
            **client_kwargs,
        )
        self.config = config or GovernanceConfig()
        self.agents = {agent.name: agent for agent in agents}
        self.max_total_turns = max_total_turns

        # Track conversation state
        self._turn_counts: Dict[str, int] = {}
        self._total_turns = 0
        self._conversation_id: Optional[str] = None

    def register_agent(self, agent: GovernedAgent) -> None:
        """Register an additional agent."""
        self.agents[agent.name] = agent

    def start_conversation(self, conversation_id: str) -> None:
        """Start a new conversation, resetting turn counts."""
        self._conversation_id = conversation_id
        self._turn_counts = {}
        self._total_turns = 0

        self.client.emit('conversation_start', {
            'conversation_id': conversation_id,
            'agents': list(self.agents.keys()),
        }, category='audit')

    # =========================================================================
    # Governance Checks
    # =========================================================================

    async def can_handoff(
        self,
        from_agent: str,
        to_agent: str,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> EvaluateResult:
        """
        Check if a handoff between agents is allowed.

        Args:
            from_agent: Source agent name
            to_agent: Target agent name
            context: Handoff context
            user_id: User identifier

        Returns:
            EvaluateResult with allowed status
        """
        # Check local restrictions first
        from_config = self.agents.get(from_agent)
        if from_config and not from_config.can_handoff_to(to_agent):
            return EvaluateResult(
                allowed=False,
                reason=f"Agent '{from_agent}' not allowed to hand off to '{to_agent}'",
            )

        # Check with Zentinelle
        result = self.client.evaluate(
            action='agent_handoff',
            user_id=user_id,
            context={
                'from_agent': from_agent,
                'to_agent': to_agent,
                'conversation_id': self._conversation_id,
                **(context or {}),
            },
        )

        self.client.emit('handoff_evaluated', {
            'from_agent': from_agent,
            'to_agent': to_agent,
            'allowed': result.allowed,
            'reason': result.reason,
        }, category='audit', user_id=user_id)

        return result

    async def can_use_tool(
        self,
        agent_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> EvaluateResult:
        """
        Check if an agent can use a specific tool.

        Args:
            agent_name: Agent name
            tool_name: Tool name
            arguments: Tool arguments
            user_id: User identifier

        Returns:
            EvaluateResult
        """
        # Check local restrictions
        agent_config = self.agents.get(agent_name)
        if agent_config and not agent_config.can_use_tool(tool_name):
            return EvaluateResult(
                allowed=False,
                reason=f"Agent '{agent_name}' not allowed to use tool '{tool_name}'",
            )

        # Check with Zentinelle
        result = self.client.evaluate(
            action='tool_call',
            user_id=user_id,
            context={
                'agent_name': agent_name,
                'tool': tool_name,
                'arguments': arguments or {},
            },
        )

        return result

    def check_turn_limit(self, agent_name: str) -> bool:
        """
        Check if agent has exceeded turn limits.

        Returns:
            True if agent can continue, False if limit exceeded
        """
        # Check total turns
        if self._total_turns >= self.max_total_turns:
            return False

        # Check agent-specific turns
        agent_config = self.agents.get(agent_name)
        if agent_config:
            agent_turns = self._turn_counts.get(agent_name, 0)
            if agent_turns >= agent_config.max_turns:
                return False

        return True

    # =========================================================================
    # Turn Tracking
    # =========================================================================

    async def track_turn(
        self,
        agent_name: str,
        message: str,
        user_id: Optional[str] = None,
    ) -> EvaluateResult:
        """
        Track a conversation turn and evaluate policies.

        Args:
            agent_name: Agent name
            message: Message content
            user_id: User identifier

        Returns:
            EvaluateResult

        Raises:
            PolicyViolationError: If turn limit exceeded
        """
        # Increment turn counters
        self._total_turns += 1
        self._turn_counts[agent_name] = self._turn_counts.get(agent_name, 0) + 1

        # Check limits
        if not self.check_turn_limit(agent_name):
            result = EvaluateResult(
                allowed=False,
                reason=f"Turn limit exceeded for agent '{agent_name}'",
            )
            if not self.config.fail_open:
                raise PolicyViolationError(result.reason, result)
            return result

        # Evaluate with Zentinelle
        result = self.client.evaluate(
            action='agent_turn',
            user_id=user_id,
            context={
                'agent_name': agent_name,
                'turn_number': self._turn_counts[agent_name],
                'total_turns': self._total_turns,
                'content_length': len(message),
            },
        )

        self.client.emit('agent_turn', {
            'agent_name': agent_name,
            'turn_number': self._turn_counts[agent_name],
            'total_turns': self._total_turns,
        }, category='telemetry', user_id=user_id)

        return result

    # =========================================================================
    # Human-in-the-Loop
    # =========================================================================

    async def request_approval(
        self,
        agent_name: str,
        action: str,
        context: Dict[str, Any],
        user_id: Optional[str] = None,
        timeout_seconds: int = 300,
    ) -> bool:
        """
        Request human approval for an action.

        Args:
            agent_name: Agent requesting approval
            action: Action requiring approval
            context: Action context
            user_id: User identifier
            timeout_seconds: Timeout for approval

        Returns:
            True if approved, False otherwise
        """
        agent_config = self.agents.get(agent_name)

        # Check if action requires approval
        if agent_config and action not in agent_config.require_approval_for:
            return True

        # Request approval via Zentinelle
        result = self.client.evaluate(
            action='human_approval_required',
            user_id=user_id,
            context={
                'agent_name': agent_name,
                'action': action,
                'context': context,
                'timeout_seconds': timeout_seconds,
            },
        )

        self.client.emit('approval_requested', {
            'agent_name': agent_name,
            'action': action,
            'approved': result.allowed,
        }, category='audit', user_id=user_id)

        return result.allowed

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def end_conversation(self) -> None:
        """End the current conversation and emit summary."""
        self.client.emit('conversation_end', {
            'conversation_id': self._conversation_id,
            'total_turns': self._total_turns,
            'turn_counts': self._turn_counts,
        }, category='audit')

        self._conversation_id = None

    def shutdown(self) -> None:
        """Shutdown and flush events."""
        if self._conversation_id:
            self.end_conversation()
        self.client.shutdown()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()
