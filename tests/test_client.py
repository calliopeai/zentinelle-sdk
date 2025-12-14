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


class TestEvaluateFailOpen:
    """Tests for evaluate method fail-open behavior."""

    def test_evaluate_validates_allowed_field(self):
        """Evaluate should raise if 'allowed' field is missing (not fail-open)."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
            )
            # Mock _post_for_evaluate to return response without 'allowed'
            with patch.object(client, '_post_for_evaluate', return_value={'reason': 'test'}):
                with pytest.raises(ZentinelleError, match="missing required 'allowed' field"):
                    client.evaluate("test_action")
            client._running = False

    def test_evaluate_accepts_fail_open_response(self):
        """Evaluate should accept response without 'allowed' if fail_open=True."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
            )
            # Mock _post_for_evaluate to return fail-open response
            with patch.object(client, '_post_for_evaluate', return_value={
                'allowed': True,
                'reason': 'fail_open',
                'fail_open': True,
            }):
                result = client.evaluate("test_action")
                assert result.allowed is True
                assert result.fail_open is True
            client._running = False

    def test_evaluate_result_has_fail_open_field(self):
        """EvaluateResult should have fail_open field."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
            )
            with patch.object(client, '_post_for_evaluate', return_value={
                'allowed': False,
                'reason': 'blocked by policy',
            }):
                result = client.evaluate("test_action")
                assert result.allowed is False
                assert result.fail_open is False
            client._running = False


class TestEventBufferBounds:
    """Tests for event buffer memory leak prevention."""

    def test_max_buffer_size_calculated_correctly(self):
        """Max buffer should be 10x normal or 1000, whichever is larger."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            # Small buffer: max should be 1000
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
                event_buffer_size=50,
            )
            assert client._max_buffer_size == 1000
            client._running = False

            # Large buffer: max should be 10x
            client2 = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
                event_buffer_size=200,
            )
            assert client2._max_buffer_size == 2000
            client2._running = False

    def test_buffer_drops_oldest_when_at_max(self):
        """Buffer should drop oldest events when at max capacity."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
                event_buffer_size=10,  # max will be 1000
            )
            # Override max for testing
            client._max_buffer_size = 5

            # Fill buffer to max
            for i in range(5):
                client.emit(f"event_{i}", {"index": i})

            assert len(client._event_buffer) == 5
            assert client._event_buffer[0]['payload']['index'] == 0

            # Add one more - should drop oldest
            client.emit("event_5", {"index": 5})

            assert len(client._event_buffer) == 5
            # First event should now be index 1 (index 0 was dropped)
            assert client._event_buffer[0]['payload']['index'] == 1
            # Last event should be index 5
            assert client._event_buffer[-1]['payload']['index'] == 5

            client._running = False
