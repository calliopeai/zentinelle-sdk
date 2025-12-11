"""
Type definitions for Sentinel SDK.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class PolicyConfig:
    """A policy configuration returned from Sentinel."""
    id: str
    name: str
    type: str
    enforcement: str
    config: Dict[str, Any]


@dataclass
class EvaluateResult:
    """Result from policy evaluation."""
    allowed: bool
    reason: Optional[str] = None
    policies_evaluated: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


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
