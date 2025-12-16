"""
Tests for SentinelClient.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import time
import threading
from datetime import datetime, timezone

from sentinel_sdk import (
    SentinelClient,
    SentinelError,
    SentinelConnectionError,
    SentinelAuthError,
    SentinelRateLimitError,
    RetryConfig,
    CircuitBreaker,
)
from sentinel_sdk.types import PolicyConfig, EvaluateResult, ConfigResult


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


class TestSentinelClientInit:
    """Tests for SentinelClient initialization."""

    def test_basic_init(self):
        with patch.object(SentinelClient, '_flush_loop'):
            client = SentinelClient(
                endpoint="https://sentinel.example.com",
                api_key="sk_agent_test",
                agent_type="test",
                auto_heartbeat=False,
            )
            assert client.endpoint == "https://sentinel.example.com"
            assert client.api_key == "sk_agent_test"
            assert client.agent_type == "test"
            client._running = False

    def test_strips_trailing_slash(self):
        with patch.object(SentinelClient, '_flush_loop'):
            client = SentinelClient(
                endpoint="https://sentinel.example.com/",
                api_key="sk_agent_test",
                agent_type="test",
                auto_heartbeat=False,
            )
            assert client.endpoint == "https://sentinel.example.com"
            client._running = False


class TestSentinelClientHeaders:
    """Tests for header generation."""

    def test_headers_with_api_key(self):
        with patch.object(SentinelClient, '_flush_loop'):
            client = SentinelClient(
                endpoint="https://sentinel.example.com",
                api_key="sk_agent_test",
                agent_type="test",
                auto_heartbeat=False,
            )
            headers = client._headers()
            assert headers['X-Sentinel-Key'] == "sk_agent_test"
            assert headers['Content-Type'] == "application/json"
            client._running = False

    def test_headers_with_org_id(self):
        with patch.object(SentinelClient, '_flush_loop'):
            client = SentinelClient(
                endpoint="https://sentinel.example.com",
                api_key="sk_agent_test",
                agent_type="test",
                org_id="org-123",
                auto_heartbeat=False,
            )
            headers = client._headers()
            assert headers['X-Sentinel-Org'] == "org-123"
            client._running = False


class TestSentinelExceptions:
    """Tests for exception classes."""

    def test_base_exception(self):
        with pytest.raises(SentinelError):
            raise SentinelError("test error")

    def test_connection_error(self):
        with pytest.raises(SentinelConnectionError):
            raise SentinelConnectionError("connection failed")

    def test_auth_error(self):
        with pytest.raises(SentinelAuthError):
            raise SentinelAuthError("invalid key")

    def test_rate_limit_error(self):
        error = SentinelRateLimitError("rate limited", retry_after=30)
        assert error.retry_after == 30

    def test_exception_hierarchy(self):
        assert issubclass(SentinelConnectionError, SentinelError)
        assert issubclass(SentinelAuthError, SentinelError)
        assert issubclass(SentinelRateLimitError, SentinelError)


@pytest.fixture
def mock_client():
    """Create a client with mocked background threads."""
    with patch.object(SentinelClient, '_flush_loop'), \
         patch.object(SentinelClient, '_heartbeat_loop'):
        client = SentinelClient(
            endpoint="https://sentinel.example.com",
            api_key="sk_agent_test",
            agent_type="jupyterhub",
            agent_id="agent-123",
            auto_heartbeat=False,
        )
        yield client
        client._running = False


class TestRegister:
    """Tests for register() method."""

    def test_register_success(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'agent_id': 'new-agent-456',
            'api_key': 'sk_new_key',
            'config': {'max_servers': 10},
            'policies': [
                {'id': 'p1', 'name': 'Policy 1', 'type': 'spawn', 'enforcement': 'enforce', 'config': {}}
            ],
        }

        with patch('requests.post', return_value=mock_response):
            result = mock_client.register(capabilities=['lab', 'chat'], metadata={'version': '1.0'})

        assert result.agent_id == 'new-agent-456'
        assert result.api_key == 'sk_new_key'
        assert result.config == {'max_servers': 10}
        assert len(result.policies) == 1
        assert result.policies[0].name == 'Policy 1'
        # Verify client state updated
        assert mock_client.agent_id == 'new-agent-456'
        assert mock_client.api_key == 'sk_new_key'
        assert mock_client._registered is True

    def test_register_auth_error(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 401

        with patch('requests.post', return_value=mock_response):
            with pytest.raises(SentinelAuthError):
                mock_client.register(capabilities=['lab'])


class TestGetConfig:
    """Tests for get_config() method."""

    def test_get_config_fresh(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'agent_id': 'agent-123',
            'config': {'setting': 'value'},
            'policies': [
                {'id': 'p1', 'name': 'Test Policy', 'type': 'spawn', 'enforcement': 'enforce', 'config': {}}
            ],
            'updated_at': '2024-01-01T00:00:00Z',
        }

        with patch('requests.get', return_value=mock_response):
            result = mock_client.get_config()

        assert result.config == {'setting': 'value'}
        assert len(result.policies) == 1
        assert result.policies[0].name == 'Test Policy'

    def test_get_config_uses_cache(self, mock_client):
        # First call - should make HTTP request
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'agent_id': 'agent-123',
            'config': {'setting': 'cached'},
            'policies': [
                {'id': 'p1', 'name': 'Cached Policy', 'type': 'spawn', 'enforcement': 'enforce', 'config': {}}
            ],
            'updated_at': '2024-01-01T00:00:00Z',
        }

        with patch('requests.get', return_value=mock_response) as mock_get:
            result1 = mock_client.get_config()
            result2 = mock_client.get_config()

        # Should only have made one HTTP call
        assert mock_get.call_count == 1
        assert result2.config == {'setting': 'cached'}
        # Verify policies are cached too (this was the bug we fixed)
        assert len(result2.policies) == 1
        assert result2.policies[0].name == 'Cached Policy'

    def test_get_config_force_refresh(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'agent_id': 'agent-123',
            'config': {'setting': 'value'},
            'policies': [],
            'updated_at': '2024-01-01T00:00:00Z',
        }

        with patch('requests.get', return_value=mock_response) as mock_get:
            mock_client.get_config()
            mock_client.get_config(force_refresh=True)

        # Should have made two HTTP calls
        assert mock_get.call_count == 2


class TestGetSecrets:
    """Tests for get_secrets() method."""

    def test_get_secrets_success(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'secrets': {'API_KEY': 'secret123', 'DB_PASSWORD': 'dbpass'},
        }

        with patch('requests.get', return_value=mock_response):
            secrets = mock_client.get_secrets()

        assert secrets['API_KEY'] == 'secret123'
        assert secrets['DB_PASSWORD'] == 'dbpass'

    def test_get_secret_convenience(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'secrets': {'API_KEY': 'secret123'},
        }

        with patch('requests.get', return_value=mock_response):
            value = mock_client.get_secret('API_KEY')
            missing = mock_client.get_secret('MISSING', default='default_val')

        assert value == 'secret123'
        assert missing == 'default_val'

    def test_get_secrets_uses_cache(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'secrets': {'KEY': 'val'}}

        with patch('requests.get', return_value=mock_response) as mock_get:
            mock_client.get_secrets()
            mock_client.get_secrets()

        assert mock_get.call_count == 1


class TestEvaluate:
    """Tests for evaluate() and can_spawn() methods."""

    def test_evaluate_allowed(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'allowed': True,
            'reason': None,
            'policies_evaluated': [{'id': 'p1', 'result': 'allow'}],
            'warnings': [],
            'context': {},
        }

        with patch('requests.post', return_value=mock_response):
            result = mock_client.evaluate('spawn', user_id='user123', context={'service': 'lab'})

        assert result.allowed is True
        assert len(result.policies_evaluated) == 1

    def test_evaluate_denied(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'allowed': False,
            'reason': 'User exceeded spawn limit',
            'policies_evaluated': [],
            'warnings': ['Approaching limit'],
            'context': {},
        }

        with patch('requests.post', return_value=mock_response):
            result = mock_client.evaluate('spawn', user_id='user123')

        assert result.allowed is False
        assert result.reason == 'User exceeded spawn limit'
        assert 'Approaching limit' in result.warnings

    def test_can_spawn_convenience(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'allowed': True,
            'policies_evaluated': [],
            'warnings': [],
            'context': {},
        }

        with patch('requests.post', return_value=mock_response) as mock_post:
            result = mock_client.can_spawn(
                user_id='user123',
                service='lab',
                instance_size='small',
                current_server_count=2
            )

        assert result.allowed is True
        # Verify the context was passed correctly
        call_data = mock_post.call_args[1]['json']
        assert call_data['action'] == 'spawn'
        assert call_data['context']['service'] == 'lab'
        assert call_data['context']['instance_size'] == 'small'
        assert call_data['context']['current_server_count'] == 2


class TestEvents:
    """Tests for event emission."""

    def test_emit_buffers_events(self, mock_client):
        mock_client.emit('test_event', {'key': 'value'}, user_id='user123')

        assert len(mock_client._event_buffer) == 1
        event = mock_client._event_buffer[0]
        assert event['type'] == 'test_event'
        assert event['payload'] == {'key': 'value'}
        assert event['user_id'] == 'user123'
        assert 'timestamp' in event

    def test_emit_spawn_convenience(self, mock_client):
        mock_client.emit_spawn('user123', 'lab', 'medium')

        assert len(mock_client._event_buffer) == 1
        event = mock_client._event_buffer[0]
        assert event['type'] == 'spawn'
        assert event['category'] == 'audit'
        assert event['payload']['service'] == 'lab'

    def test_emit_ai_request_convenience(self, mock_client):
        mock_client.emit_ai_request('user123', 'openai', 'gpt-4', 100, 50)

        event = mock_client._event_buffer[0]
        assert event['type'] == 'ai_request'
        assert event['payload']['input_tokens'] == 100
        assert event['payload']['output_tokens'] == 50

    def test_flush_events_success(self, mock_client):
        mock_client._registered = True
        mock_client.emit('event1', {})
        mock_client.emit('event2', {})

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'accepted': 2, 'batch_id': 'batch-123'}

        with patch('requests.post', return_value=mock_response):
            result = mock_client.flush_events()

        assert result.accepted == 2
        assert result.batch_id == 'batch-123'
        assert len(mock_client._event_buffer) == 0

    def test_flush_events_requeues_on_failure(self, mock_client):
        mock_client._registered = True
        mock_client.emit('event1', {})

        with patch('requests.post', side_effect=Exception("Network error")):
            result = mock_client.flush_events()

        assert result is None
        # Events should be re-queued
        assert len(mock_client._event_buffer) == 1

    def test_auto_flush_when_buffer_full(self, mock_client):
        mock_client._registered = True
        mock_client._event_buffer_size = 3

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'accepted': 3, 'batch_id': 'batch-123'}

        with patch('requests.post', return_value=mock_response) as mock_post:
            mock_client.emit('event1', {})
            mock_client.emit('event2', {})
            # This should trigger a flush
            mock_client.emit('event3', {})

        assert mock_post.called


class TestShutdown:
    """Tests for shutdown behavior."""

    def test_shutdown_flushes_remaining_events(self, mock_client):
        mock_client._registered = True
        mock_client.emit('final_event', {})

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'accepted': 1, 'batch_id': 'batch-final'}

        with patch('requests.post', return_value=mock_response) as mock_post:
            mock_client.shutdown(timeout=0.1)

        assert mock_post.called

    def test_context_manager(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'accepted': 0, 'batch_id': 'b'}

        with patch('requests.post', return_value=mock_response):
            with mock_client as client:
                client._registered = True
                client.emit('event', {})
            # After context exit, client should be shut down
            assert client._running is False


class TestHTTPErrorHandling:
    """Tests for HTTP error handling."""

    def test_handles_401_auth_error(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 401

        with patch('requests.get', return_value=mock_response):
            with pytest.raises(SentinelAuthError, match="Invalid or expired API key"):
                mock_client.get_config()

    def test_handles_403_forbidden(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 403

        with patch('requests.get', return_value=mock_response):
            with pytest.raises(SentinelAuthError, match="Access denied"):
                mock_client.get_config()

    def test_handles_429_rate_limit(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {'Retry-After': '30'}

        with patch('requests.get', return_value=mock_response):
            with pytest.raises(SentinelRateLimitError) as exc_info:
                mock_client.get_config()
            assert exc_info.value.retry_after == 30

    def test_handles_500_server_error(self, mock_client):
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch('requests.get', return_value=mock_response):
            with pytest.raises(SentinelConnectionError, match="Server error"):
                mock_client.get_config()

    def test_retries_on_connection_error(self, mock_client):
        mock_client._retry_config = RetryConfig(max_retries=2, base_delay=0.01, jitter=False)

        import requests as req
        with patch('requests.get', side_effect=req.ConnectionError("Connection refused")):
            with pytest.raises(SentinelConnectionError, match="Failed after 3 attempts"):
                mock_client.get_config()


class TestHeartbeat:
    """Tests for heartbeat functionality."""

    def test_heartbeat_sends_status(self, mock_client):
        mock_client._registered = True

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch('requests.post', return_value=mock_response) as mock_post:
            mock_client.heartbeat(status='healthy', metrics={'cpu': 50})

        call_data = mock_post.call_args[1]['json']
        assert call_data['status'] == 'healthy'
        assert call_data['metrics'] == {'cpu': 50}

    def test_heartbeat_skipped_when_not_registered(self, mock_client):
        mock_client._registered = False

        with patch('requests.post') as mock_post:
            mock_client.heartbeat()

        assert not mock_post.called
