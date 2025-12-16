"""
Zentinelle SDK Client - Main client class for AI agent governance.
"""
import threading
import time
import logging
import random
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from functools import wraps

from .types import (
    EvaluateResult,
    PolicyConfig,
    RegisterResult,
    ConfigResult,
    SecretsResult,
    EventsResult,
    HeartbeatResult,
    ModelUsage,
    EventCategory,
)

logger = logging.getLogger(__name__)


class ZentinelleError(Exception):
    """Base exception for Zentinelle SDK errors."""
    pass


class ZentinelleConnectionError(ZentinelleError):
    """Raised when unable to connect to Zentinelle."""
    pass


class ZentinelleAuthError(ZentinelleError):
    """Raised when authentication fails."""
    pass


class ZentinelleRateLimitError(ZentinelleError):
    """Raised when rate limit is exceeded."""
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class RetryConfig:
    """Configuration for retry behavior."""
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number (0-indexed)."""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)

        if self.jitter:
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0, delay)


class CircuitBreaker:
    """
    Circuit breaker pattern for failing fast when service is down.

    States:
    - CLOSED: Normal operation, requests go through
    - OPEN: Service is down, fail immediately
    - HALF_OPEN: Testing if service recovered
    """

    CLOSED = 'closed'
    OPEN = 'open'
    HALF_OPEN = 'half_open'

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN:
                if time.time() - (self._last_failure_time or 0) > self.recovery_timeout:
                    self._state = self.HALF_OPEN
                    self._half_open_calls = 0
            return self._state

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            if self._state == self.HALF_OPEN:
                self._half_open_calls += 1
                if self._half_open_calls >= self.half_open_max_calls:
                    self._state = self.CLOSED
                    self._failure_count = 0
                    logger.info("Circuit breaker recovered to CLOSED state")
            elif self._state == self.CLOSED:
                self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == self.HALF_OPEN:
                self._state = self.OPEN
                logger.warning("Circuit breaker back to OPEN state")
            elif self._failure_count >= self.failure_threshold:
                self._state = self.OPEN
                logger.warning(
                    f"Circuit breaker OPEN after {self._failure_count} failures"
                )

    def can_execute(self) -> bool:
        """Check if a call should be allowed."""
        return self.state != self.OPEN

    def __call__(self, func):
        """Decorator usage."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not self.can_execute():
                raise ZentinelleConnectionError(
                    "Circuit breaker is OPEN - Zentinelle service appears to be down"
                )

            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception:
                self.record_failure()
                raise

        return wrapper


class ZentinelleClient:
    """
    Zentinelle SDK client for AI agent governance.

    Features:
    - Automatic heartbeats in background
    - Buffered event emission (batch sends)
    - Config/secrets caching
    - Graceful degradation when Zentinelle unavailable
    - Framework-agnostic (works with any AI framework)

    Usage:
        client = ZentinelleClient(
            endpoint="https://api.zentinelle.ai",
            api_key="sk_agent_...",
            agent_type="langchain",
        )

        # On startup
        config = client.register(
            capabilities=["chat", "tools"],
            metadata={"version": "1.0.0"}
        )

        # Get secrets (cached)
        secrets = client.get_secrets()
        openai_key = secrets["OPENAI_API_KEY"]

        # Before critical actions
        result = client.evaluate("tool_call", user_id="user123", context={...})
        if not result.allowed:
            raise PermissionError(result.reason)

        # Track model usage
        client.track_usage(ModelUsage.from_openai(response))

        # Emit events (buffered, async)
        client.emit("tool_call", {"tool": "web_search"})
    """

    DEFAULT_ENDPOINT = "https://api.zentinelle.ai"

    def __init__(
        self,
        api_key: str,
        agent_type: str,
        endpoint: Optional[str] = None,
        agent_id: Optional[str] = None,
        org_id: Optional[str] = None,
        auto_heartbeat: bool = True,
        heartbeat_interval: int = 60,
        event_buffer_size: int = 100,
        event_flush_interval: int = 5,
        config_cache_ttl: int = 300,
        secrets_cache_ttl: int = 60,
        timeout: int = 30,
        retry_config: Optional[RetryConfig] = None,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_recovery: float = 30.0,
        fail_open: bool = False,
    ):
        """
        Initialize Zentinelle client.

        Args:
            api_key: API key for authentication
            agent_type: Type of agent (langchain, autogen, crewai, custom, etc.)
            endpoint: Zentinelle API endpoint URL (defaults to cloud)
            agent_id: Optional agent ID (generated on registration if not provided)
            org_id: Organization ID (optional, derived from API key if not provided)
            auto_heartbeat: Enable automatic heartbeat sending
            heartbeat_interval: Seconds between heartbeats
            event_buffer_size: Max events to buffer before flush
            event_flush_interval: Seconds between event flushes
            config_cache_ttl: Config cache TTL in seconds
            secrets_cache_ttl: Secrets cache TTL in seconds
            timeout: HTTP request timeout in seconds
            retry_config: Custom retry configuration
            circuit_breaker_threshold: Number of failures before opening circuit
            circuit_breaker_recovery: Seconds to wait before testing recovery
            fail_open: If True, allow actions when Zentinelle is unreachable

        Raises:
            ValueError: If api_key or agent_type is invalid
        """
        # Validate required parameters
        if not api_key or len(api_key) < 10:
            raise ValueError("api_key is required and must be at least 10 characters")
        # Validate API key format (should start with sk_agent_ or similar prefix)
        valid_prefixes = ('sk_agent_', 'sk_test_', 'sk_live_', 'znt_')
        if not any(api_key.startswith(prefix) for prefix in valid_prefixes):
            logger.warning(
                "API key does not match expected format (sk_agent_*, sk_test_*, sk_live_*, znt_*). "
                "This may indicate an invalid key."
            )
        if not agent_type:
            raise ValueError("agent_type is required")

        self.endpoint = (endpoint or self.DEFAULT_ENDPOINT).rstrip('/')
        # Enforce HTTPS for security (API keys are transmitted in headers)
        if not self.endpoint.startswith('https://'):
            raise ValueError("endpoint must use HTTPS for security")
        self.api_key = api_key
        self.agent_type = agent_type
        self.agent_id = agent_id
        self.org_id = org_id
        self.timeout = timeout
        self.fail_open = fail_open

        # Retry and circuit breaker config
        self._retry_config = retry_config or RetryConfig()
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_breaker_threshold,
            recovery_timeout=circuit_breaker_recovery,
        )

        # Config
        self._heartbeat_interval = heartbeat_interval
        self._event_buffer_size = event_buffer_size
        self._event_flush_interval = event_flush_interval
        self._config_cache_ttl = timedelta(seconds=config_cache_ttl)
        self._secrets_cache_ttl = timedelta(seconds=secrets_cache_ttl)

        # Caches (protected by _cache_lock for thread safety)
        self._config_cache: Optional[Dict] = None
        self._config_cache_time: Optional[datetime] = None
        self._policies_cache: List[PolicyConfig] = []
        self._secrets_cache: Optional[Dict] = None
        self._secrets_cache_time: Optional[datetime] = None
        self._cache_lock = threading.Lock()

        # Event buffer
        self._event_buffer: List[Dict] = []
        self._buffer_lock = threading.Lock()
        # Maximum buffer size to prevent memory leaks (10x normal or 1000, whichever is larger)
        self._max_buffer_size = max(event_buffer_size * 10, 1000)

        # Background threads
        self._running = True
        self._registered = False

        # Start flush thread
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="zentinelle-flush"
        )
        self._flush_thread.start()

        # Start heartbeat thread if enabled
        self._heartbeat_thread = None
        if auto_heartbeat:
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                daemon=True,
                name="zentinelle-heartbeat"
            )
            self._heartbeat_thread.start()

    # =========================================================================
    # HTTP Helpers
    # =========================================================================

    def _headers(self) -> Dict[str, str]:
        """Get request headers."""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'zentinelle-python/0.1.0',
        }
        if self.api_key:
            headers['X-Zentinelle-Key'] = self.api_key
        if self.org_id:
            headers['X-Zentinelle-Org'] = self.org_id
        return headers

    def _handle_response(self, response: requests.Response) -> Dict:
        """Handle HTTP response, converting errors to appropriate exceptions."""
        if response.status_code == 401:
            raise ZentinelleAuthError("Invalid or expired API key")

        if response.status_code == 403:
            raise ZentinelleAuthError("Access denied - insufficient permissions")

        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            raise ZentinelleRateLimitError(
                "Rate limit exceeded",
                retry_after=retry_after
            )

        if response.status_code >= 500:
            raise ZentinelleConnectionError(
                f"Server error: {response.status_code} - {response.text[:200]}"
            )

        response.raise_for_status()
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError as e:
            raise ZentinelleConnectionError(
                f"Invalid JSON response from server: {e}"
            ) from e

    def _get(self, path: str) -> Dict:
        """Make GET request with retry logic."""
        if not self._circuit_breaker.can_execute():
            if self.fail_open:
                logger.warning("Circuit breaker OPEN, failing open")
                return {}
            raise ZentinelleConnectionError(
                "Circuit breaker is OPEN - Zentinelle service appears to be down"
            )

        url = f"{self.endpoint}/api/v1{path}"
        last_exception: Optional[Exception] = None

        for attempt in range(self._retry_config.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=self._headers(),
                    timeout=self.timeout
                )
                result = self._handle_response(response)
                self._circuit_breaker.record_success()
                return result

            except ZentinelleRateLimitError:
                self._circuit_breaker.record_success()
                raise

            except ZentinelleAuthError:
                raise

            except (requests.RequestException, ZentinelleConnectionError) as e:
                last_exception = e
                self._circuit_breaker.record_failure()

                if attempt >= self._retry_config.max_retries:
                    if self.fail_open:
                        logger.warning(f"Failed after {attempt + 1} attempts, failing open")
                        return {}
                    raise ZentinelleConnectionError(f"Failed after {attempt + 1} attempts: {e}") from e

                delay = self._retry_config.get_delay(attempt)
                logger.warning(
                    f"GET {path} failed (attempt {attempt + 1}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)

        # This should be unreachable, but guard against edge cases
        if last_exception:
            raise last_exception
        raise ZentinelleConnectionError(f"Request to {path} failed unexpectedly")

    def _post(self, path: str, data: Dict, is_evaluate: bool = False) -> Dict:
        """Make POST request with retry logic."""
        if not self._circuit_breaker.can_execute():
            if self.fail_open:
                logger.warning("Circuit breaker OPEN, failing open")
                if is_evaluate:
                    return {'allowed': True, 'reason': 'fail_open', 'fail_open': True}
                return {}
            raise ZentinelleConnectionError(
                "Circuit breaker is OPEN - Zentinelle service appears to be down"
            )

        url = f"{self.endpoint}/api/v1{path}"
        last_exception: Optional[Exception] = None

        for attempt in range(self._retry_config.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    json=data,
                    headers=self._headers(),
                    timeout=self.timeout
                )
                result = self._handle_response(response)
                self._circuit_breaker.record_success()
                return result

            except ZentinelleRateLimitError:
                self._circuit_breaker.record_success()
                raise

            except ZentinelleAuthError:
                raise

            except (requests.RequestException, ZentinelleConnectionError) as e:
                last_exception = e
                self._circuit_breaker.record_failure()

                if attempt >= self._retry_config.max_retries:
                    if self.fail_open:
                        logger.warning(f"Failed after {attempt + 1} attempts, failing open")
                        if is_evaluate:
                            return {'allowed': True, 'reason': 'fail_open', 'fail_open': True}
                        return {}
                    raise ZentinelleConnectionError(f"Failed after {attempt + 1} attempts: {e}") from e

                delay = self._retry_config.get_delay(attempt)
                logger.warning(
                    f"POST {path} failed (attempt {attempt + 1}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)

        # This should be unreachable, but guard against edge cases
        if last_exception:
            raise last_exception
        raise ZentinelleConnectionError(f"Request to {path} failed unexpectedly")

    def _post_for_evaluate(self, path: str, data: Dict) -> Dict:
        """Make POST request for evaluate endpoint with proper fail-open handling."""
        return self._post(path, data, is_evaluate=True)

    # =========================================================================
    # Registration
    # =========================================================================

    def register(
        self,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        name: Optional[str] = None,
    ) -> RegisterResult:
        """
        Register agent on startup.

        Args:
            capabilities: List of agent capabilities (e.g., ["chat", "tools", "code"])
            metadata: Optional metadata (version, cluster, etc.)
            name: Optional display name

        Returns:
            RegisterResult with agent_id, api_key, config, and policies
        """
        response = self._post('/agents/register', {
            'agent_id': self.agent_id,
            'agent_type': self.agent_type,
            'capabilities': capabilities or [],
            'metadata': metadata or {},
            'name': name,
        })

        self.agent_id = response['agent_id']
        self._registered = True

        policies = [
            PolicyConfig(**p) for p in response.get('policies', [])
        ]

        # Cache config and policies
        with self._cache_lock:
            self._config_cache = response.get('config', {})
            self._policies_cache = policies
            self._config_cache_time = datetime.now(timezone.utc)

        if response.get('api_key'):
            self.api_key = response['api_key']

        logger.info(f"Registered agent: {self.agent_id}")

        return RegisterResult(
            agent_id=response['agent_id'],
            api_key=response.get('api_key', ''),
            config=response.get('config', {}),
            policies=policies,
        )

    # =========================================================================
    # Configuration
    # =========================================================================

    def _require_agent_id(self) -> None:
        """Raise error if agent_id is not set (i.e., register() not called)."""
        if not self.agent_id:
            raise ZentinelleError(
                "Agent not registered. Call register() first or provide agent_id in constructor."
            )

    def get_config(self, force_refresh: bool = False) -> ConfigResult:
        """
        Get current config and policies (cached).

        Args:
            force_refresh: Bypass cache and fetch fresh config

        Returns:
            ConfigResult with config and policies

        Raises:
            ZentinelleError: If agent is not registered
        """
        self._require_agent_id()
        # Thread-safe cache check
        with self._cache_lock:
            if not force_refresh and self._config_cache is not None and self._config_cache_time:
                if datetime.now(timezone.utc) - self._config_cache_time < self._config_cache_ttl:
                    return ConfigResult(
                        agent_id=self.agent_id,
                        config=self._config_cache.copy(),  # Return copy to prevent mutation
                        policies=self._policies_cache,
                        updated_at=self._config_cache_time,
                    )

        response = self._get(f'/agents/{self.agent_id}/config')

        policies = [
            PolicyConfig(**p) for p in response.get('policies', [])
        ]

        with self._cache_lock:
            self._config_cache = response.get('config', {})
            self._policies_cache = policies
            self._config_cache_time = datetime.now(timezone.utc)

        return ConfigResult(
            agent_id=response.get('agent_id', self.agent_id),
            config=response.get('config', {}),
            policies=policies,
            updated_at=datetime.fromisoformat(
                response.get('updated_at', datetime.now(timezone.utc).isoformat()).replace('Z', '+00:00')
            ),
        )

    def get_policies(self, policy_types: Optional[List[str]] = None) -> List[PolicyConfig]:
        """Get effective policies for this agent."""
        config_result = self.get_config()
        policies = config_result.policies

        if policy_types:
            policies = [p for p in policies if p.type in policy_types]

        return policies

    # =========================================================================
    # Secrets
    # =========================================================================

    def get_secrets(self, force_refresh: bool = False) -> Dict[str, str]:
        """
        Get secrets this agent can access (cached).

        Args:
            force_refresh: Bypass cache and fetch fresh secrets

        Returns:
            Dictionary of secret name -> value (copy to prevent mutation)

        Raises:
            ZentinelleError: If agent is not registered
        """
        self._require_agent_id()
        # Thread-safe cache check
        with self._cache_lock:
            if not force_refresh and self._secrets_cache and self._secrets_cache_time:
                if datetime.now(timezone.utc) - self._secrets_cache_time < self._secrets_cache_ttl:
                    return self._secrets_cache.copy()  # Return copy to prevent mutation

        response = self._get(f'/agents/{self.agent_id}/secrets')

        with self._cache_lock:
            self._secrets_cache = response.get('secrets', {})
            self._secrets_cache_time = datetime.now(timezone.utc)
            return self._secrets_cache.copy()  # Return copy to prevent mutation

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a single secret value."""
        secrets = self.get_secrets()
        return secrets.get(key, default)

    # =========================================================================
    # Policy Evaluation
    # =========================================================================

    def evaluate(
        self,
        action: str,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> EvaluateResult:
        """
        Evaluate policies for an action.

        Args:
            action: The action to evaluate (e.g., "tool_call", "model_request")
            user_id: User performing the action
            context: Additional context for evaluation

        Returns:
            EvaluateResult with allowed status and details

        Raises:
            ZentinelleError: If agent is not registered
        """
        self._require_agent_id()
        response = self._post_for_evaluate('/evaluate', {
            'agent_id': self.agent_id,
            'action': action,
            'user_id': user_id or '',
            'context': context or {},
        })

        # Check for fail-open response
        is_fail_open = response.get('fail_open', False)

        # Critical: validate that 'allowed' field is present (unless fail-open)
        # Never default to True - this would bypass security
        if not is_fail_open and 'allowed' not in response:
            raise ZentinelleError("Invalid response: missing required 'allowed' field")

        return EvaluateResult(
            allowed=response.get('allowed', True) if is_fail_open else response['allowed'],
            reason=response.get('reason'),
            policies_evaluated=response.get('policies_evaluated', []),
            warnings=response.get('warnings', []),
            context=response.get('context', {}),
            fail_open=is_fail_open,
        )

    def can_use_model(self, model: str, provider: str = 'openai') -> EvaluateResult:
        """Check if a specific model can be used."""
        return self.evaluate(
            action='model_request',
            context={'model': model, 'provider': provider}
        )

    def can_call_tool(self, tool_name: str, user_id: Optional[str] = None) -> EvaluateResult:
        """Check if a tool can be called."""
        return self.evaluate(
            action='tool_call',
            user_id=user_id,
            context={'tool': tool_name}
        )

    # =========================================================================
    # Usage Tracking
    # =========================================================================

    def track_usage(self, usage: ModelUsage) -> None:
        """
        Track model usage for cost policies.

        Args:
            usage: ModelUsage object (use from_openai/from_anthropic helpers)
        """
        self.emit('model_usage', {
            'provider': usage.provider,
            'model': usage.model,
            'input_tokens': usage.input_tokens,
            'output_tokens': usage.output_tokens,
            'estimated_cost': usage.estimated_cost,
        }, category=EventCategory.TELEMETRY.value)

    # =========================================================================
    # Events
    # =========================================================================

    def emit(
        self,
        event_type: str,
        payload: Optional[Dict] = None,
        category: str = 'telemetry',
        user_id: Optional[str] = None,
    ) -> None:
        """
        Emit an event (buffered, async).

        Args:
            event_type: Type of event (tool_call, model_request, etc.)
            payload: Event data
            category: Event category (telemetry, audit, alert, compliance)
            user_id: User associated with event
        """
        event = {
            'type': event_type,
            'category': category,
            'payload': payload or {},
            'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
            'user_id': user_id or '',
        }

        with self._buffer_lock:
            # Enforce max buffer size to prevent memory leaks
            if len(self._event_buffer) >= self._max_buffer_size:
                dropped = len(self._event_buffer) - self._max_buffer_size + 1
                self._event_buffer = self._event_buffer[dropped:]
                logger.warning(f"Event buffer at max capacity, dropped {dropped} oldest events")

            self._event_buffer.append(event)

            if len(self._event_buffer) >= self._event_buffer_size:
                self._flush_events_sync()

    def emit_tool_call(
        self,
        tool_name: str,
        user_id: Optional[str] = None,
        inputs: Optional[Dict] = None,
        outputs: Optional[Dict] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Emit a tool call event."""
        self.emit('tool_call', {
            'tool': tool_name,
            'inputs': inputs or {},
            'outputs': outputs or {},
            'duration_ms': duration_ms,
        }, category='audit', user_id=user_id)

    def emit_model_request(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        user_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Emit a model request event."""
        self.emit('model_request', {
            'provider': provider,
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'duration_ms': duration_ms,
        }, category='telemetry', user_id=user_id)

    def flush_events(self) -> Optional[EventsResult]:
        """Manually flush buffered events."""
        with self._buffer_lock:
            return self._flush_events_sync()

    def _flush_events_sync(self) -> Optional[EventsResult]:
        """Flush events (called with lock held)."""
        if not self._event_buffer or not self.agent_id:
            return None

        events = self._event_buffer
        self._event_buffer = []

        try:
            response = self._post('/events', {
                'agent_id': self.agent_id,
                'events': events,
            })
            logger.debug(f"Flushed {len(events)} events")
            return EventsResult(
                accepted=response.get('accepted', len(events)),
                batch_id=response.get('batch_id', ''),
            )
        except (ZentinelleConnectionError, ZentinelleRateLimitError, requests.RequestException) as e:
            logger.warning(f"Failed to flush events: {e}")
            # Re-queue events on transient failures (lock already held by caller)
            if len(self._event_buffer) + len(events) <= self._max_buffer_size:
                self._event_buffer = events + self._event_buffer
            else:
                logger.warning(f"Failed to flush {len(events)} events and buffer is full, events dropped")
            return None
        except ZentinelleAuthError as e:
            # Auth errors should not requeue - configuration issue
            logger.error(f"Authentication failed while flushing events: {e}")
            return None

    def _flush_loop(self) -> None:
        """Background thread: flush events periodically."""
        while self._running:
            time.sleep(self._event_flush_interval)
            if self._registered:
                with self._buffer_lock:
                    self._flush_events_sync()

    # =========================================================================
    # Heartbeat
    # =========================================================================

    def heartbeat(
        self,
        status: str = 'healthy',
        metrics: Optional[Dict] = None,
    ) -> Optional[HeartbeatResult]:
        """
        Send heartbeat to Zentinelle.

        Args:
            status: Health status (healthy, degraded, unhealthy)
            metrics: Optional metrics to include

        Returns:
            HeartbeatResult or None if failed
        """
        if not self._registered or not self.agent_id:
            return None

        try:
            response = self._post('/heartbeat', {
                'agent_id': self.agent_id,
                'status': status,
                'metrics': metrics or {},
            })
            logger.debug(f"Sent heartbeat: {status}")
            return HeartbeatResult(
                acknowledged=response.get('acknowledged', True),
                config_changed=response.get('config_changed', False),
                next_heartbeat_seconds=response.get('next_heartbeat_seconds', 60),
            )
        except (ZentinelleConnectionError, ZentinelleRateLimitError, requests.RequestException) as e:
            logger.warning(f"Failed to send heartbeat: {e}")
            return None
        except ZentinelleAuthError as e:
            logger.error(f"Authentication failed during heartbeat: {e}")
            return None

    def _heartbeat_loop(self) -> None:
        """Background thread: send heartbeats periodically."""
        while self._running:
            time.sleep(self._heartbeat_interval)
            if self._registered:
                result = self.heartbeat()
                if result and result.config_changed:
                    self.get_config(force_refresh=True)

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def shutdown(self, timeout: float = 5.0) -> None:
        """
        Graceful shutdown: stop threads and flush remaining events.

        Args:
            timeout: Maximum time to wait for threads to finish (seconds)
        """
        logger.info("Shutting down Zentinelle client")
        self._running = False

        # Flush remaining events
        with self._buffer_lock:
            self._flush_events_sync()

        # Wait for background threads to finish
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=timeout)
            if self._flush_thread.is_alive():
                logger.warning("Flush thread did not terminate within timeout")

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=timeout)
            if self._heartbeat_thread.is_alive():
                logger.warning("Heartbeat thread did not terminate within timeout")

        # Clear sensitive data from memory
        with self._cache_lock:
            self._secrets_cache = None
            self._secrets_cache_time = None
            self._config_cache = None
            self._policies_cache = []
            self._config_cache_time = None

        # Clear API key (note: Python strings are immutable, so we can only remove reference)
        self.api_key = ""
        self.org_id = None

    def __repr__(self) -> str:
        """Return string representation with masked sensitive fields."""
        masked_key = f"{self.api_key[:8]}...{self.api_key[-4:]}" if len(self.api_key) > 12 else "***"
        return (
            f"ZentinelleClient(agent_id={self.agent_id!r}, "
            f"agent_type={self.agent_type!r}, "
            f"endpoint={self.endpoint!r}, "
            f"api_key={masked_key!r})"
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()
