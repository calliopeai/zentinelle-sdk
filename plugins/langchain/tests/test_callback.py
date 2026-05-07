"""Tests for ZentinelleCallbackHandler."""
import uuid
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def mock_client():
    with patch('zentinelle_langchain.callback.ZentinelleClient') as MockClient:
        client = MockClient.return_value
        client.emit = MagicMock()
        client.track_usage = MagicMock()
        client.register = MagicMock(return_value=MagicMock(agent_id='test'))
        client.shutdown = MagicMock()
        yield client, MockClient


class TestCallbackHandlerInit:
    def test_creates_client(self, mock_client):
        client, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(
            api_key='sk_agent_test_key_123',
            agent_type='langchain',
        )
        MockClient.assert_called_once()
        assert handler.client is client

    def test_passes_endpoint(self, mock_client):
        client, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        ZentinelleCallbackHandler(
            api_key='sk_agent_test_key_123',
            agent_type='langchain',
            endpoint='https://my-zentinelle.example.com',
        )
        _, kwargs = MockClient.call_args
        assert kwargs['endpoint'] == 'https://my-zentinelle.example.com'


class TestLLMCallbacks:
    def test_on_llm_start_emits_event(self, mock_client):
        client, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')

        handler.on_llm_start(
            serialized={'kwargs': {'model_name': 'gpt-4o'}, 'id': ['openai']},
            prompts=['Hello'],
            run_id=uuid.uuid4(),
        )

        client.emit.assert_called_once()
        args, kwargs = client.emit.call_args
        assert args[0] == 'llm_start'
        assert args[1]['model'] == 'gpt-4o'

    def test_on_llm_end_tracks_usage(self, mock_client):
        client, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')

        run_id = uuid.uuid4()
        handler.on_llm_start(
            serialized={'kwargs': {'model_name': 'gpt-4o'}, 'id': ['openai']},
            prompts=['Hello'],
            run_id=run_id,
        )

        from langchain_core.outputs import LLMResult, Generation
        result = LLMResult(
            generations=[[Generation(text='Hi there')]],
            llm_output={
                'model_name': 'gpt-4o',
                'token_usage': {'prompt_tokens': 10, 'completion_tokens': 5},
            },
        )

        handler.on_llm_end(result, run_id=run_id)

        client.track_usage.assert_called_once()
        usage = client.track_usage.call_args[0][0]
        assert usage.input_tokens == 10
        assert usage.output_tokens == 5

    def test_on_llm_error_emits_alert(self, mock_client):
        client, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')

        run_id = uuid.uuid4()
        handler._start_times[run_id] = 1000.0

        handler.on_llm_error(ValueError('rate limited'), run_id=run_id)

        client.emit.assert_called_once()
        args, kwargs = client.emit.call_args
        assert args[0] == 'llm_error'
        assert kwargs['category'] == 'alert'
        assert run_id not in handler._start_times


class TestToolCallbacks:
    def test_on_tool_start_emits_audit(self, mock_client):
        client, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')

        handler.on_tool_start(
            serialized={'name': 'web_search'},
            input_str='search query',
            run_id=uuid.uuid4(),
        )

        client.emit.assert_called_once()
        args, kwargs = client.emit.call_args
        assert args[0] == 'tool_start'
        assert args[1]['tool'] == 'web_search'
        assert kwargs['category'] == 'audit'

    def test_on_tool_end_reports_duration(self, mock_client):
        client, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')

        run_id = uuid.uuid4()
        handler.on_tool_start(
            serialized={'name': 'calculator'},
            input_str='2+2',
            run_id=run_id,
        )
        handler.on_tool_end('4', run_id=run_id)

        assert client.emit.call_count == 2
        end_call = client.emit.call_args_list[1]
        assert end_call[0][0] == 'tool_end'
        assert end_call[0][1]['duration_ms'] is not None


class TestProviderDetection:
    def test_detects_openai(self, mock_client):
        _, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')
        assert handler._detect_provider('gpt-4o') == 'openai'

    def test_detects_anthropic(self, mock_client):
        _, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')
        assert handler._detect_provider('claude-3-5-sonnet-20240620') == 'anthropic'

    def test_detects_google(self, mock_client):
        _, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')
        assert handler._detect_provider('gemini-1.5-pro') == 'google'

    def test_detects_from_llm_output(self, mock_client):
        _, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')
        assert handler._detect_provider('unknown-model', {'system_fingerprint': 'fp_abc'}) == 'openai'


class TestTimingCleanup:
    def test_stale_entries_cleaned(self, mock_client):
        import time
        _, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')

        stale_id = uuid.uuid4()
        handler._start_times[stale_id] = time.time() - 600
        handler._last_cleanup_time = 0

        handler._cleanup_stale_timings()

        assert stale_id not in handler._start_times


class TestShutdown:
    def test_shutdown_calls_client(self, mock_client):
        client, MockClient = mock_client
        from zentinelle_langchain import ZentinelleCallbackHandler
        handler = ZentinelleCallbackHandler(api_key='sk_agent_test_key_123', agent_type='langchain')
        handler.shutdown()
        client.shutdown.assert_called_once()
