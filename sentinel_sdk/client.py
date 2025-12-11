"""
Sentinel SDK Client - Main client class for agent integration.
"""
import threading
import time
import logging
import random
import requests
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import asdict
from functools import wraps

from sentinel_sdk.types import (
    EvaluateResult,
    PolicyConfig,
    RegisterResult,
    ConfigResult,
    SecretsResult,
    EventsResult,
)

logger = logging.getLogger(__name__)


class SentinelError(Exception):
    """Base exception for Sentinel SDK errors."""
    pass


class SentinelConnectionError(SentinelError):
    """Raised when unable to connect to Sentinel."""
    pass


class SentinelAuthError(SentinelError):
    """Raised when authentication fails."""
    pass


class SentinelRateLimitError(SentinelError):
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
            # Add random jitter (±25%)
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0, delay)


def with_retry(
    retry_config: Optional[RetryConfig] = None,
    retryable_exceptions: tuple = (requests.RequestException, SentinelConnectionError),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    Decorator for retrying functions with exponential backoff.

    Args:
        retry_config: Retry configuration
        retryable_exceptions: Tuple of exceptions to retry on
        on_retry: Callback called before each retry (exception, attempt)
    """
    config = retry_config or RetryConfig()

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt >= config.max_retries:
                        raise

                    delay = config.get_delay(attempt)

                    if on_retry:
                        on_retry(e, attempt)

                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{config.max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)

            raise last_exception

        return wrapper
    return decorator


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
                # Check if recovery timeout has passed
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
                    # Recovered
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
                # Failed during recovery test
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
                raise SentinelConnectionError(
                    "Circuit breaker is OPEN - Sentinel service appears to be down"
                )

            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise

        return wrapper


class SentinelClient:
    """
    Sentinel SDK client for agent integration.

    Features:
    - Automatic heartbeats in background
    - Buffered event emission (batch sends)
    - Config/secrets caching
    - Graceful degradation when Sentinel unavailable

    Usage:
        client = SentinelClient(
            endpoint="https://sentinel.example.com",
            api_key="sk_agent_...",
            agent_type="jupyterhub",
        )

        # On startup
        config = client.register(
            capabilities=["lab", "chat"],
            metadata={"version": "1.0.0"}
        )

        # Get secrets (cached)
        secrets = client.get_secrets()
        openai_key = secrets["OPENAI_API_KEY"]

        # Before critical actions
        result = client.evaluate("spawn", user_id="user123", context={...})
        if not result.allowed:
            raise PermissionError(result.reason)

        # Emit events (buffered, async)
        client.emit("spawn", {"user_id": "user123", "service": "lab"})
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        agent_type: str,
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
    ):
        """
        Initialize Sentinel client.

        Args:
            endpoint: Sentinel API endpoint URL
            api_key: API key for authentication
            agent_type: Type of agent (jupyterhub, chat, langchain, etc.)
            agent_id: Optional agent ID (generated on registration if not provided)
            org_id: Organization ID (required for registration)
            auto_heartbeat: Enable automatic heartbeat sending
            heartbeat_interval: Seconds between heartbeats
            event_buffer_size: Max events to buffer before flush
            event_flush_interval: Seconds between event flushes
            config_cache_ttl: Config cache TTL in seconds
            secrets_cache_ttl: Secrets cache TTL in seconds
            timeout: HTTP request timeout in seconds
            retry_config: Custom retry configuration (uses defaults if not provided)
            circuit_breaker_threshold: Number of failures before opening circuit
            circuit_breaker_recovery: Seconds to wait before testing recovery
        """
        self.endpoint = endpoint.rstrip('/')
        self.api_key = api_key
        self.agent_type = agent_type
        self.agent_id = agent_id
        self.org_id = org_id
        self.timeout = timeout

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

        # Caches
        self._config_cache: Optional[Dict] = None
        self._config_cache_time: Optional[datetime] = None
        self._secrets_cache: Optional[Dict] = None
        self._secrets_cache_time: Optional[datetime] = None

        # Event buffer
        self._event_buffer: List[Dict] = []
        self._buffer_lock = threading.Lock()

        # Background threads
        self._running = True
        self._registered = False

        # Start flush thread
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="sentinel-flush"
        )
        self._flush_thread.start()

        # Start heartbeat thread if enabled
        if auto_heartbeat:
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                daemon=True,
                name="sentinel-heartbeat"
            )
            self._heartbeat_thread.start()

    # =========================================================================
    # HTTP Helpers
    # =========================================================================

    def _headers(self) -> Dict[str, str]:
        """Get request headers."""
        headers = {
            'Content-Type': 'application/json',
        }
        if self.api_key:
            headers['X-Sentinel-Key'] = self.api_key
        if self.org_id:
            headers['X-Sentinel-Org'] = self.org_id
        return headers

    def _handle_response(self, response: requests.Response) -> Dict:
        """Handle HTTP response, converting errors to appropriate exceptions."""
        if response.status_code == 401:
            raise SentinelAuthError("Invalid or expired API key")

        if response.status_code == 403:
            raise SentinelAuthError("Access denied - insufficient permissions")

        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            raise SentinelRateLimitError(
                "Rate limit exceeded",
                retry_after=retry_after
            )

        if response.status_code >= 500:
            raise SentinelConnectionError(
                f"Server error: {response.status_code} - {response.text[:200]}"
            )

        response.raise_for_status()
        return response.json()

    def _get(self, path: str) -> Dict:
        """Make GET request with retry logic."""
        if not self._circuit_breaker.can_execute():
            raise SentinelConnectionError(
                "Circuit breaker is OPEN - Sentinel service appears to be down"
            )

        url = f"{self.endpoint}/api/sentinel/v1{path}"
        last_exception = None

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

            except SentinelRateLimitError as e:
                # Don't retry rate limits, respect retry-after
                self._circuit_breaker.record_success()  # Rate limit isn't a failure
                raise

            except SentinelAuthError:
                # Don't retry auth errors
                raise

            except (requests.RequestException, SentinelConnectionError) as e:
                last_exception = e
                self._circuit_breaker.record_failure()

                if attempt >= self._retry_config.max_retries:
                    raise SentinelConnectionError(f"Failed after {attempt + 1} attempts: {e}")

                delay = self._retry_config.get_delay(attempt)
                logger.warning(
                    f"GET {path} failed (attempt {attempt + 1}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)

        raise last_exception

    def _post(self, path: str, data: Dict) -> Dict:
        """Make POST request with retry logic."""
        if not self._circuit_breaker.can_execute():
            raise SentinelConnectionError(
                "Circuit breaker is OPEN - Sentinel service appears to be down"
            )

        url = f"{self.endpoint}/api/sentinel/v1{path}"
        last_exception = None

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

            except SentinelRateLimitError as e:
                # Don't retry rate limits
                self._circuit_breaker.record_success()
                raise

            except SentinelAuthError:
                # Don't retry auth errors
                raise

            except (requests.RequestException, SentinelConnectionError) as e:
                last_exception = e
                self._circuit_breaker.record_failure()

                if attempt >= self._retry_config.max_retries:
                    raise SentinelConnectionError(f"Failed after {attempt + 1} attempts: {e}")

                delay = self._retry_config.get_delay(attempt)
                logger.warning(
                    f"POST {path} failed (attempt {attempt + 1}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)

        raise last_exception

    # =========================================================================
    # Registration
    # =========================================================================

    def register(
        self,
        capabilities: List[str],
        metadata: Optional[Dict] = None,
        name: Optional[str] = None,
    ) -> RegisterResult:
        """
        Register agent on startup.
        Returns initial config, policies, and API key (only time key is visible).

        Args:
            capabilities: List of agent capabilities (e.g., ["lab", "chat"])
            metadata: Optional metadata (version, cluster, etc.)
            name: Optional display name

        Returns:
            RegisterResult with agent_id, api_key, config, and policies
        """
        response = self._post('/register', {
            'agent_id': self.agent_id,
            'agent_type': self.agent_type,
            'capabilities': capabilities,
            'metadata': metadata or {},
            'name': name,
        })

        self.agent_id = response['agent_id']
        self._registered = True

        # Cache the config
        self._config_cache = response.get('config', {})
        self._config_cache_time = datetime.utcnow()

        # Update API key if new one provided
        if response.get('api_key'):
            self.api_key = response['api_key']

        policies = [
            PolicyConfig(**p) for p in response.get('policies', [])
        ]

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

    def get_config(self, force_refresh: bool = False) -> ConfigResult:
        """
        Get current config and policies.
        Results are cached for config_cache_ttl seconds.

        Args:
            force_refresh: Bypass cache and fetch fresh config

        Returns:
            ConfigResult with config and policies
        """
        # Check cache
        if not force_refresh and self._config_cache and self._config_cache_time:
            if datetime.utcnow() - self._config_cache_time < self._config_cache_ttl:
                return ConfigResult(
                    agent_id=self.agent_id,
                    config=self._config_cache,
                    policies=[],  # Would need to cache policies too
                    updated_at=self._config_cache_time,
                )

        response = self._get(f'/config/{self.agent_id}')

        self._config_cache = response.get('config', {})
        self._config_cache_time = datetime.utcnow()

        policies = [
            PolicyConfig(**p) for p in response.get('policies', [])
        ]

        return ConfigResult(
            agent_id=response['agent_id'],
            config=response.get('config', {}),
            policies=policies,
            updated_at=datetime.fromisoformat(response['updated_at'].replace('Z', '+00:00')),
        )

    def get_policies(self, policy_types: Optional[List[str]] = None) -> List[PolicyConfig]:
        """
        Get effective policies for this agent.

        Args:
            policy_types: Optional filter by policy types

        Returns:
            List of PolicyConfig objects
        """
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
        Get secrets this agent can access.
        Results are cached for secrets_cache_ttl seconds.

        Args:
            force_refresh: Bypass cache and fetch fresh secrets

        Returns:
            Dictionary of secret name -> value
        """
        # Check cache
        if not force_refresh and self._secrets_cache and self._secrets_cache_time:
            if datetime.utcnow() - self._secrets_cache_time < self._secrets_cache_ttl:
                return self._secrets_cache

        response = self._get(f'/secrets/{self.agent_id}')

        self._secrets_cache = response.get('secrets', {})
        self._secrets_cache_time = datetime.utcnow()

        return self._secrets_cache

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a single secret value.

        Args:
            key: Secret key name
            default: Default value if not found

        Returns:
            Secret value or default
        """
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
        Use this before critical operations like spawning servers.

        Args:
            action: The action to evaluate (e.g., "spawn", "tool_call")
            user_id: User performing the action
            context: Additional context for evaluation

        Returns:
            EvaluateResult with allowed status and details
        """
        response = self._post('/evaluate', {
            'agent_id': self.agent_id,
            'action': action,
            'user_id': user_id or '',
            'context': context or {},
        })

        return EvaluateResult(
            allowed=response['allowed'],
            reason=response.get('reason'),
            policies_evaluated=response.get('policies_evaluated', []),
            warnings=response.get('warnings', []),
            context=response.get('context', {}),
        )

    def can_spawn(
        self,
        user_id: str,
        service: str,
        instance_size: str,
        current_server_count: int = 0,
    ) -> EvaluateResult:
        """
        Convenience method to check if spawning is allowed.

        Args:
            user_id: User requesting spawn
            service: Service type (lab, chat, etc.)
            instance_size: Instance size requested
            current_server_count: Current number of servers

        Returns:
            EvaluateResult
        """
        return self.evaluate(
            action='spawn',
            user_id=user_id,
            context={
                'service': service,
                'instance_size': instance_size,
                'current_server_count': current_server_count,
            }
        )

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
        Events are batched and sent periodically.

        Args:
            event_type: Type of event (spawn, stop, ai_request, etc.)
            payload: Event data
            category: Event category (telemetry, audit, alert)
            user_id: User associated with event
        """
        event = {
            'type': event_type,
            'category': category,
            'payload': payload or {},
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'user_id': user_id or '',
        }

        with self._buffer_lock:
            self._event_buffer.append(event)

            # Flush if buffer is full
            if len(self._event_buffer) >= self._event_buffer_size:
                self._flush_events_sync()

    def emit_spawn(self, user_id: str, service: str, instance_size: str) -> None:
        """Convenience: emit spawn event."""
        self.emit('spawn', {
            'user_id': user_id,
            'service': service,
            'instance_size': instance_size,
        }, category='audit', user_id=user_id)

    def emit_stop(self, user_id: str, service: str, duration_seconds: int) -> None:
        """Convenience: emit stop event."""
        self.emit('stop', {
            'user_id': user_id,
            'service': service,
            'duration_seconds': duration_seconds,
        }, category='audit', user_id=user_id)

    def emit_ai_request(
        self,
        user_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Convenience: emit AI request event for token tracking."""
        self.emit('ai_request', {
            'user_id': user_id,
            'provider': provider,
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
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
                accepted=response['accepted'],
                batch_id=response['batch_id'],
            )
        except Exception as e:
            logger.warning(f"Failed to flush events: {e}")
            # Re-queue events on failure (with limit)
            with self._buffer_lock:
                if len(self._event_buffer) < self._event_buffer_size * 2:
                    self._event_buffer = events + self._event_buffer
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

    def heartbeat(self, status: str = 'healthy', metrics: Optional[Dict] = None) -> None:
        """
        Send heartbeat to Sentinel.
        Called automatically if auto_heartbeat is enabled.

        Args:
            status: Health status (healthy, degraded, unhealthy)
            metrics: Optional metrics to include
        """
        if not self._registered or not self.agent_id:
            return

        try:
            self._post('/heartbeat', {
                'agent_id': self.agent_id,
                'status': status,
                'metrics': metrics or {},
            })
            logger.debug(f"Sent heartbeat: {status}")
        except Exception as e:
            logger.warning(f"Failed to send heartbeat: {e}")

    def _heartbeat_loop(self) -> None:
        """Background thread: send heartbeats periodically."""
        while self._running:
            time.sleep(self._heartbeat_interval)
            if self._registered:
                self.heartbeat()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def shutdown(self) -> None:
        """Graceful shutdown: stop threads and flush remaining events."""
        logger.info("Shutting down Sentinel client")
        self._running = False

        # Final flush
        with self._buffer_lock:
            self._flush_events_sync()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()
