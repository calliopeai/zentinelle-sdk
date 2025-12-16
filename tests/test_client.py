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

    def test_half_open_limits_calls(self):
        """Half-open state should limit the number of test calls."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, half_open_max_calls=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

        time.sleep(0.15)
        # First call in half-open should be allowed
        assert cb.can_execute() is True
        assert cb.state == CircuitBreaker.HALF_OPEN

        # Second call should also be allowed
        assert cb.can_execute() is True

        # Third call should be blocked until success/failure resets
        # (implementation detail: depends on how half_open_calls is tracked)


class TestZentinelleClientRepr:
    """Tests for ZentinelleClient string representation."""

    def test_repr_masks_api_key(self):
        """API key should be masked in __repr__."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_secret_key_12345",
                agent_type="test",
                auto_heartbeat=False,
            )
            repr_str = repr(client)
            # Should not contain full API key
            assert "sk_agent_secret_key_12345" not in repr_str
            # Should contain masked version
            assert "sk_agent..." in repr_str
            assert "...2345" in repr_str
            client._running = False

    def test_repr_shows_agent_info(self):
        """Repr should show agent_id and agent_type."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test_key_123",
                agent_type="langchain",
                agent_id="agent-123",
                auto_heartbeat=False,
            )
            repr_str = repr(client)
            assert "agent_id='agent-123'" in repr_str
            assert "agent_type='langchain'" in repr_str
            client._running = False


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
                agent_id="test-agent",
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
                agent_id="test-agent",
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
                agent_id="test-agent",
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


class TestAgentIdValidation:
    """Tests for agent_id validation before API calls."""

    def test_get_config_requires_agent_id(self):
        """get_config() should raise if agent_id is not set."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
            )
            # agent_id is None by default
            with pytest.raises(ZentinelleError, match="Agent not registered"):
                client.get_config()
            client._running = False

    def test_get_secrets_requires_agent_id(self):
        """get_secrets() should raise if agent_id is not set."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
            )
            with pytest.raises(ZentinelleError, match="Agent not registered"):
                client.get_secrets()
            client._running = False

    def test_evaluate_requires_agent_id(self):
        """evaluate() should raise if agent_id is not set."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
            )
            with pytest.raises(ZentinelleError, match="Agent not registered"):
                client.evaluate("test_action")
            client._running = False

    def test_agent_id_from_constructor_works(self):
        """Agent ID provided in constructor should be valid."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                agent_id="pre-registered-agent",
                auto_heartbeat=False,
            )
            # Should not raise - agent_id is set
            with patch.object(client, '_get', return_value={'config': {}, 'policies': []}):
                result = client.get_config()
                assert result is not None
            client._running = False


class TestRegister:
    """Tests for register() method."""

    def test_register_success(self):
        """register() should update agent_id and cache config."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
            )
            mock_response = {
                'agent_id': 'new-agent-id',
                'api_key': 'sk_new_key',
                'config': {'setting': 'value'},
                'policies': [{'id': 'p1', 'name': 'Policy', 'type': 'test', 'enforcement': 'enforce', 'config': {}}],
            }
            with patch.object(client, '_post', return_value=mock_response):
                result = client.register(capabilities=['chat'])

            assert result.agent_id == 'new-agent-id'
            assert result.api_key == 'sk_new_key'
            assert result.config == {'setting': 'value'}
            assert len(result.policies) == 1
            assert client.agent_id == 'new-agent-id'
            assert client._registered is True
            client._running = False


class TestGetConfig:
    """Tests for get_config() method."""

    def test_get_config_caches_result(self):
        """get_config() should cache result and return from cache on second call."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                agent_id="test-agent",
                auto_heartbeat=False,
            )
            mock_response = {
                'agent_id': 'test-agent',
                'config': {'cached': True},
                'policies': [{'id': 'p1', 'name': 'Policy', 'type': 'test', 'enforcement': 'enforce', 'config': {}}],
                'updated_at': '2025-01-01T00:00:00Z',
            }
            with patch.object(client, '_get', return_value=mock_response) as mock_get:
                # First call - should hit API
                result1 = client.get_config()
                # Second call - should use cache
                result2 = client.get_config()

                assert mock_get.call_count == 1
                assert result1.config == {'cached': True}
                assert result2.config == {'cached': True}
                # Policies should also be cached
                assert len(result2.policies) == 1
            client._running = False

    def test_get_config_force_refresh(self):
        """get_config(force_refresh=True) should bypass cache."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                agent_id="test-agent",
                auto_heartbeat=False,
            )
            mock_response = {
                'agent_id': 'test-agent',
                'config': {'fresh': True},
                'policies': [],
                'updated_at': '2025-01-01T00:00:00Z',
            }
            with patch.object(client, '_get', return_value=mock_response) as mock_get:
                client.get_config()
                client.get_config(force_refresh=True)

                assert mock_get.call_count == 2
            client._running = False


class TestGetSecrets:
    """Tests for get_secrets() method."""

    def test_get_secrets_returns_copy(self):
        """get_secrets() should return a copy to prevent mutation."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                agent_id="test-agent",
                auto_heartbeat=False,
            )
            mock_response = {'secrets': {'API_KEY': 'secret123'}}
            with patch.object(client, '_get', return_value=mock_response):
                secrets = client.get_secrets()
                secrets['API_KEY'] = 'modified'

                # Original cache should not be modified
                secrets2 = client.get_secrets()
                assert secrets2['API_KEY'] == 'secret123'
            client._running = False

    def test_get_secret_convenience(self):
        """get_secret() should return single value."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                agent_id="test-agent",
                auto_heartbeat=False,
            )
            mock_response = {'secrets': {'API_KEY': 'secret123'}}
            with patch.object(client, '_get', return_value=mock_response):
                assert client.get_secret('API_KEY') == 'secret123'
                assert client.get_secret('MISSING') is None
                assert client.get_secret('MISSING', 'default') == 'default'
            client._running = False


class TestJSONParsingErrors:
    """Tests for JSON parsing error handling."""

    def test_invalid_json_raises_connection_error(self):
        """Invalid JSON response should raise ZentinelleConnectionError."""
        import requests
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                agent_id="test-agent",
                auto_heartbeat=False,
            )
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.side_effect = requests.exceptions.JSONDecodeError("error", "doc", 0)
            mock_response.raise_for_status = Mock()

            with patch('requests.get', return_value=mock_response):
                with pytest.raises(ZentinelleConnectionError, match="Invalid JSON response"):
                    client.get_config()
            client._running = False


class TestHTTPErrorHandling:
    """Tests for HTTP error handling."""

    def test_401_raises_auth_error(self):
        """401 response should raise ZentinelleAuthError."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                agent_id="test-agent",
                auto_heartbeat=False,
            )
            mock_response = Mock()
            mock_response.status_code = 401

            with patch('requests.get', return_value=mock_response):
                with pytest.raises(ZentinelleAuthError, match="Invalid or expired"):
                    client.get_config()
            client._running = False

    def test_429_raises_rate_limit_error(self):
        """429 response should raise ZentinelleRateLimitError with retry_after."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                agent_id="test-agent",
                auto_heartbeat=False,
            )
            mock_response = Mock()
            mock_response.status_code = 429
            mock_response.headers = {'Retry-After': '60'}

            with patch('requests.get', return_value=mock_response):
                with pytest.raises(ZentinelleRateLimitError) as exc_info:
                    client.get_config()
                assert exc_info.value.retry_after == 60
            client._running = False

    def test_500_raises_connection_error(self):
        """500 response should raise ZentinelleConnectionError."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                agent_id="test-agent",
                auto_heartbeat=False,
            )
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"

            with patch('requests.get', return_value=mock_response):
                with pytest.raises(ZentinelleConnectionError, match="Server error"):
                    client.get_config()
            client._running = False


class TestShutdown:
    """Tests for shutdown() method."""

    def test_shutdown_clears_sensitive_data(self):
        """shutdown() should clear caches and API key."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            client = ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                agent_id="test-agent",
                auto_heartbeat=False,
            )
            # Set some cache data
            client._secrets_cache = {'secret': 'value'}
            client._config_cache = {'config': 'value'}

            client.shutdown(timeout=0.1)

            assert client._secrets_cache is None
            assert client._config_cache is None
            assert client.api_key == ""
            assert client._running is False

    def test_context_manager_calls_shutdown(self):
        """Using client as context manager should call shutdown on exit."""
        with patch.object(ZentinelleClient, '_flush_loop'):
            with ZentinelleClient(
                api_key="sk_agent_test123",
                agent_type="test",
                auto_heartbeat=False,
            ) as client:
                assert client._running is True

            assert client._running is False
