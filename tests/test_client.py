"""
Tests for ZentinelleClient.
"""
import pytest
from unittest.mock import Mock, patch
import time

from zentinelle import (
    ZentinelleClient,
    ZentinelleError,
    ZentinelleConnectionError,
    ZentinelleAuthError,
    ZentinelleRateLimitError,
    RetryConfig,
    CircuitBreaker,
)


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_default_config(self):
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0
        assert config.jitter is True

    def test_custom_config(self):
        config = RetryConfig(
            max_retries=5,
            base_delay=0.5,
            max_delay=30.0,
            exponential_base=3.0,
            jitter=False,
        )
        assert config.max_retries == 5
        assert config.base_delay == 0.5
        assert config.max_delay == 30.0
        assert config.exponential_base == 3.0
        assert config.jitter is False

    def test_get_delay_without_jitter(self):
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=False)
        assert config.get_delay(0) == 1.0
        assert config.get_delay(1) == 2.0
        assert config.get_delay(2) == 4.0
        assert config.get_delay(3) == 8.0

    def test_get_delay_respects_max(self):
        config = RetryConfig(base_delay=1.0, max_delay=5.0, jitter=False)
        assert config.get_delay(10) == 5.0

    def test_get_delay_with_jitter(self):
        config = RetryConfig(base_delay=1.0, jitter=True)
        delays = [config.get_delay(0) for _ in range(10)]
        # With jitter, delays should vary
        assert len(set(delays)) > 1
        # But should be within expected range (±25%)
        for delay in delays:
            assert 0.75 <= delay <= 1.25


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.can_execute() is True

    def test_opens_after_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitBreaker.CLOSED

        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED

        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        assert cb.can_execute() is False

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        # Should still be closed because success reset count
        assert cb.state == CircuitBreaker.CLOSED

    def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitBreaker.HALF_OPEN

    def test_recovery_from_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, half_open_max_calls=2)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.15)
        assert cb.state == CircuitBreaker.HALF_OPEN

        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED

    def test_failure_in_half_open_reopens(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.15)
        assert cb.state == CircuitBreaker.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN


class TestZentinelleClientInit:
    """Tests for ZentinelleClient initialization."""

    def test_basic_init(self):
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                endpoint="https://api.zentinelle.ai",
                api_key="sk_agent_test",
                agent_type="test",
                auto_heartbeat=False,
            )
            assert client.endpoint == "https://api.zentinelle.ai"
            assert client.api_key == "sk_agent_test"
            assert client.agent_type == "test"
            client._running = False

    def test_strips_trailing_slash(self):
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                endpoint="https://api.zentinelle.ai/",
                api_key="sk_agent_test",
                agent_type="test",
                auto_heartbeat=False,
            )
            assert client.endpoint == "https://api.zentinelle.ai"
            client._running = False


class TestZentinelleClientHeaders:
    """Tests for header generation."""

    def test_headers_with_api_key(self):
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                endpoint="https://api.zentinelle.ai",
                api_key="sk_agent_test",
                agent_type="test",
                auto_heartbeat=False,
            )
            headers = client._headers()
            assert headers['X-Zentinelle-Key'] == "sk_agent_test"
            assert headers['Content-Type'] == "application/json"
            client._running = False

    def test_headers_with_org_id(self):
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                endpoint="https://api.zentinelle.ai",
                api_key="sk_agent_test",
                agent_type="test",
                org_id="org-123",
                auto_heartbeat=False,
            )
            headers = client._headers()
            assert headers['X-Zentinelle-Org'] == "org-123"
            client._running = False


class TestZentinelleExceptions:
    """Tests for exception classes."""

    def test_base_exception(self):
        with pytest.raises(ZentinelleError):
            raise ZentinelleError("test error")

    def test_connection_error(self):
        with pytest.raises(ZentinelleConnectionError):
            raise ZentinelleConnectionError("connection failed")

    def test_auth_error(self):
        with pytest.raises(ZentinelleAuthError):
            raise ZentinelleAuthError("invalid key")

    def test_rate_limit_error(self):
        error = ZentinelleRateLimitError("rate limited", retry_after=30)
        assert error.retry_after == 30

    def test_exception_hierarchy(self):
        assert issubclass(ZentinelleConnectionError, ZentinelleError)
        assert issubclass(ZentinelleAuthError, ZentinelleError)
        assert issubclass(ZentinelleRateLimitError, ZentinelleError)
