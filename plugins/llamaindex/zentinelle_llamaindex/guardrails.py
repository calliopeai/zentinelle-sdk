"""
Content guardrails for LlamaIndex RAG applications.
"""

import re
from abc import ABC, abstractmethod
from typing import Any, Optional

from zentinelle import ZentinelleClient
from zentinelle.types import EvaluateResult


class GuardrailViolation(Exception):
    """Raised when content violates a guardrail."""

    def __init__(self, guardrail: str, reason: str, content_preview: str = ""):
        self.guardrail = guardrail
        self.reason = reason
        self.content_preview = content_preview
        super().__init__(f"Guardrail '{guardrail}' violated: {reason}")


class BaseGuardrail(ABC):
    """Base class for content guardrails."""

    def __init__(self, client: ZentinelleClient, name: str):
        self._client = client
        self._name = name

    @property
    def name(self) -> str:
        """Guardrail name."""
        return self._name

    @abstractmethod
    def check(self, content: str, context: Optional[dict[str, Any]] = None) -> EvaluateResult:
        """
        Check content against the guardrail.

        Args:
            content: Content to check
            context: Additional context

        Returns:
            EvaluateResult indicating if content is allowed
        """
        pass

    def validate(
        self, content: str, context: Optional[dict[str, Any]] = None
    ) -> str:
        """
        Validate content and raise if violation detected.

        Args:
            content: Content to validate
            context: Additional context

        Returns:
            The content if allowed

        Raises:
            GuardrailViolation: If content violates guardrail
        """
        result = self.check(content, context)
        if not result.allowed:
            self._client.emit(
                category="policy_evaluation",
                action=f"guardrail_{self._name}",
                success=False,
                metadata={
                    "reason": result.reason,
                    "content_preview": content[:200],
                },
            )
            raise GuardrailViolation(
                guardrail=self._name,
                reason=result.reason or "Content blocked",
                content_preview=content[:100],
            )
        return content


class PIIGuardrail(BaseGuardrail):
    """
    Guardrail for detecting and blocking PII in content.

    Detects:
    - Email addresses
    - Phone numbers
    - SSN patterns
    - Credit card numbers
    - Custom patterns

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        guardrail = PIIGuardrail(
            client=client,
            block_on_detection=True,
            custom_patterns={"employee_id": r"EMP-\d{6}"}
        )

        # Check content
        result = guardrail.check("Contact john@example.com for help")
        # result.allowed = False

        # Or validate (raises on detection)
        safe_content = guardrail.validate(content)
    """

    # Common PII patterns
    DEFAULT_PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "phone": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "ssn": r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
        "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
        "ip_address": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    }

    def __init__(
        self,
        client: ZentinelleClient,
        block_on_detection: bool = True,
        patterns_to_check: Optional[list[str]] = None,
        custom_patterns: Optional[dict[str, str]] = None,
        redact_instead_of_block: bool = False,
    ):
        """
        Initialize PII guardrail.

        Args:
            client: Zentinelle client instance
            block_on_detection: Whether to block content with PII
            patterns_to_check: Which default patterns to check (None = all)
            custom_patterns: Additional custom regex patterns
            redact_instead_of_block: Redact PII instead of blocking
        """
        super().__init__(client, "pii")
        self._block_on_detection = block_on_detection
        self._redact_instead_of_block = redact_instead_of_block

        # Build patterns dict
        self._patterns = {}
        patterns_to_check = patterns_to_check or list(self.DEFAULT_PATTERNS.keys())
        for name in patterns_to_check:
            if name in self.DEFAULT_PATTERNS:
                self._patterns[name] = re.compile(self.DEFAULT_PATTERNS[name], re.IGNORECASE)

        if custom_patterns:
            for name, pattern in custom_patterns.items():
                self._patterns[name] = re.compile(pattern, re.IGNORECASE)

    def check(
        self, content: str, context: Optional[dict[str, Any]] = None
    ) -> EvaluateResult:
        """Check content for PII."""
        detected = []

        for name, pattern in self._patterns.items():
            matches = pattern.findall(content)
            if matches:
                detected.append(
                    {"type": name, "count": len(matches), "examples": matches[:3]}
                )

        if detected:
            # Also check with Zentinelle for additional policy
            zentinelle_result = self._client.evaluate(
                "pii_detection",
                context={
                    "detected_types": [d["type"] for d in detected],
                    "detection_count": sum(d["count"] for d in detected),
                    "content_length": len(content),
                    **(context or {}),
                },
            )

            if self._block_on_detection and not zentinelle_result.allowed:
                return EvaluateResult(
                    allowed=False,
                    reason=f"PII detected: {', '.join(d['type'] for d in detected)}",
                    policies=[],
                    metadata={"detected": detected},
                )

        return EvaluateResult(allowed=True, reason="no_pii_detected", policies=[])

    def redact(self, content: str) -> str:
        """
        Redact PII from content.

        Args:
            content: Content to redact

        Returns:
            Content with PII replaced by [REDACTED]
        """
        result = content
        for name, pattern in self._patterns.items():
            result = pattern.sub(f"[{name.upper()}_REDACTED]", result)
        return result


class ContentGuardrail(BaseGuardrail):
    """
    Guardrail for blocking inappropriate or harmful content.

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        guardrail = ContentGuardrail(
            client=client,
            blocked_topics=["violence", "illegal_activities"],
            blocked_keywords=["hack", "exploit"],
            max_length=10000
        )

        result = guardrail.check(response_content)
    """

    def __init__(
        self,
        client: ZentinelleClient,
        blocked_topics: Optional[list[str]] = None,
        blocked_keywords: Optional[list[str]] = None,
        max_length: Optional[int] = None,
        require_zentinelle_approval: bool = True,
    ):
        """
        Initialize content guardrail.

        Args:
            client: Zentinelle client instance
            blocked_topics: Topics to block
            blocked_keywords: Keywords to block
            max_length: Maximum content length
            require_zentinelle_approval: Whether to check with Zentinelle
        """
        super().__init__(client, "content")
        self._blocked_topics = blocked_topics or []
        self._blocked_keywords = [kw.lower() for kw in (blocked_keywords or [])]
        self._max_length = max_length
        self._require_zentinelle_approval = require_zentinelle_approval

    def check(
        self, content: str, context: Optional[dict[str, Any]] = None
    ) -> EvaluateResult:
        """Check content against guardrail rules."""
        content_lower = content.lower()

        # Check length
        if self._max_length and len(content) > self._max_length:
            return EvaluateResult(
                allowed=False,
                reason=f"Content exceeds max length: {len(content)} > {self._max_length}",
                policies=[],
            )

        # Check keywords
        detected_keywords = [
            kw for kw in self._blocked_keywords if kw in content_lower
        ]
        if detected_keywords:
            return EvaluateResult(
                allowed=False,
                reason=f"Blocked keywords detected: {', '.join(detected_keywords)}",
                policies=[],
            )

        # Check with Zentinelle for topic/content analysis
        if self._require_zentinelle_approval:
            return self._client.evaluate(
                "content_moderation",
                context={
                    "content_preview": content[:500],
                    "content_length": len(content),
                    "blocked_topics": self._blocked_topics,
                    **(context or {}),
                },
            )

        return EvaluateResult(allowed=True, reason="content_allowed", policies=[])


class SourceGuardrail(BaseGuardrail):
    """
    Guardrail for validating RAG source attribution.

    Ensures responses are properly grounded in retrieved sources.

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")

        guardrail = SourceGuardrail(
            client=client,
            require_sources=True,
            min_sources=1,
            allowed_source_types=["documentation", "policy"]
        )

        result = guardrail.check(
            response,
            context={"sources": retrieved_nodes}
        )
    """

    def __init__(
        self,
        client: ZentinelleClient,
        require_sources: bool = True,
        min_sources: int = 1,
        min_relevance_score: float = 0.5,
        allowed_source_types: Optional[list[str]] = None,
        blocked_source_types: Optional[list[str]] = None,
    ):
        """
        Initialize source guardrail.

        Args:
            client: Zentinelle client instance
            require_sources: Whether sources are required
            min_sources: Minimum number of sources required
            min_relevance_score: Minimum relevance score for sources
            allowed_source_types: Allowed source types
            blocked_source_types: Blocked source types
        """
        super().__init__(client, "source")
        self._require_sources = require_sources
        self._min_sources = min_sources
        self._min_relevance_score = min_relevance_score
        self._allowed_source_types = allowed_source_types
        self._blocked_source_types = blocked_source_types or []

    def check(
        self, content: str, context: Optional[dict[str, Any]] = None
    ) -> EvaluateResult:
        """Check source attribution."""
        context = context or {}
        sources = context.get("sources", [])

        # Check source requirement
        if self._require_sources and not sources:
            return EvaluateResult(
                allowed=False,
                reason="No sources provided for response",
                policies=[],
            )

        # Check minimum sources
        if len(sources) < self._min_sources:
            return EvaluateResult(
                allowed=False,
                reason=f"Insufficient sources: {len(sources)} < {self._min_sources}",
                policies=[],
            )

        # Check source scores and types
        valid_sources = []
        for source in sources:
            score = getattr(source, "score", None) or source.get("score", 1.0)
            if score < self._min_relevance_score:
                continue

            # Check source type
            metadata = getattr(source, "metadata", {}) or source.get("metadata", {})
            source_type = metadata.get("type", "unknown")

            if source_type in self._blocked_source_types:
                continue

            if self._allowed_source_types and source_type not in self._allowed_source_types:
                continue

            valid_sources.append(source)

        if len(valid_sources) < self._min_sources:
            return EvaluateResult(
                allowed=False,
                reason=f"Insufficient valid sources after filtering: {len(valid_sources)} < {self._min_sources}",
                policies=[],
            )

        # Check with Zentinelle
        return self._client.evaluate(
            "source_validation",
            context={
                "source_count": len(valid_sources),
                "source_types": [
                    (getattr(s, "metadata", {}) or s.get("metadata", {})).get("type", "unknown")
                    for s in valid_sources
                ],
                "response_length": len(content),
            },
        )
