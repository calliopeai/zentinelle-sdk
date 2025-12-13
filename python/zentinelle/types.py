"""
Type definitions for Zentinelle SDK.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


class PolicyType(str, Enum):
    """Standard policy types."""
    RATE_LIMIT = 'rate_limit'
    COST_LIMIT = 'cost_limit'
    PII_FILTER = 'pii_filter'
    PROMPT_INJECTION = 'prompt_injection'
    SYSTEM_PROMPT = 'system_prompt'
    MODEL_RESTRICTION = 'model_restriction'
    HUMAN_OVERSIGHT = 'human_oversight'
    AGENT_CAPABILITY = 'agent_capability'
    AGENT_MEMORY = 'agent_memory'
    DATA_RETENTION = 'data_retention'
    AUDIT_LOG = 'audit_log'


class Enforcement(str, Enum):
    """Policy enforcement levels."""
    ENFORCE = 'enforce'
    WARN = 'warn'
    LOG = 'log'
    DISABLED = 'disabled'


class EventCategory(str, Enum):
    """Event categories for telemetry."""
    TELEMETRY = 'telemetry'
    AUDIT = 'audit'
    ALERT = 'alert'
    COMPLIANCE = 'compliance'


@dataclass
class PolicyConfig:
    """A policy configuration returned from Zentinelle."""
    id: str
    name: str
    type: str
    enforcement: str
    config: Dict[str, Any]
    priority: int = 100

    def is_enforced(self) -> bool:
        """Check if policy is actively enforced."""
        return self.enforcement == Enforcement.ENFORCE.value


@dataclass
class EvaluateResult:
    """Result from policy evaluation."""
    allowed: bool
    reason: Optional[str] = None
    policies_evaluated: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def require_human_approval(self) -> bool:
        """Check if human approval is required."""
        return self.context.get('require_human_approval', False)

    @property
    def blocked_policies(self) -> List[str]:
        """Get list of policies that blocked this action."""
        return [
            p['name'] for p in self.policies_evaluated
            if not p.get('passed', True)
        ]


@dataclass
class RegisterResult:
    """Result from agent registration."""
    agent_id: str
    api_key: str  # Only available on initial registration
    config: Dict[str, Any]
    policies: List[PolicyConfig]


@dataclass
class ConfigResult:
    """Result from config fetch."""
    agent_id: str
    config: Dict[str, Any]
    policies: List[PolicyConfig]
    updated_at: datetime


@dataclass
class SecretsResult:
    """Result from secrets fetch."""
    secrets: Dict[str, str]
    providers: Dict[str, Any]
    expires_at: datetime


@dataclass
class EventsResult:
    """Result from events submission."""
    accepted: int
    batch_id: str


@dataclass
class HeartbeatResult:
    """Result from heartbeat."""
    acknowledged: bool
    config_changed: bool = False
    next_heartbeat_seconds: int = 60


@dataclass
class ModelUsage:
    """Model usage tracking for cost policies."""
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: float = 0.0

    @classmethod
    def from_openai(cls, response) -> 'ModelUsage':
        """Create from OpenAI response object."""
        usage = response.usage
        return cls(
            provider='openai',
            model=response.model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
        )

    @classmethod
    def from_anthropic(cls, response) -> 'ModelUsage':
        """Create from Anthropic response object."""
        return cls(
            provider='anthropic',
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
