"""Tests for ZentinelleGuardrail and ZentinelleToolWrapper."""
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

import pytest


@dataclass
class FakeEvaluateResult:
    allowed: bool
    reason: str = None
    warnings: list = None
    fail_open: bool = False

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@pytest.fixture
def mock_zentinelle_client():
    client = MagicMock()
    client.evaluate = MagicMock()
    client.emit_tool_call = MagicMock()
    return client


class TestGuardrail:
    def test_allows_when_policy_passes(self, mock_zentinelle_client):
        mock_zentinelle_client.evaluate.return_value = FakeEvaluateResult(allowed=True)
        from zentinelle_langchain import ZentinelleGuardrail
        guard = ZentinelleGuardrail(mock_zentinelle_client)

        result = guard.invoke("Hello world")

        assert result == "Hello world"
        mock_zentinelle_client.evaluate.assert_called_once()

    def test_raises_on_block(self, mock_zentinelle_client):
        mock_zentinelle_client.evaluate.return_value = FakeEvaluateResult(
            allowed=False, reason='PII detected'
        )
        from zentinelle_langchain import ZentinelleGuardrail
        from zentinelle_langchain.guardrail import PolicyViolationError
        guard = ZentinelleGuardrail(mock_zentinelle_client)

        with pytest.raises(PolicyViolationError, match='PII detected'):
            guard.invoke("My SSN is 123-45-6789")

    def test_returns_error_dict_when_not_raising(self, mock_zentinelle_client):
        mock_zentinelle_client.evaluate.return_value = FakeEvaluateResult(
            allowed=False, reason='Blocked'
        )
        from zentinelle_langchain import ZentinelleGuardrail
        guard = ZentinelleGuardrail(mock_zentinelle_client, raise_on_block=False)

        result = guard.invoke("test")

        assert result['blocked'] is True
        assert result['error'] == 'Blocked'

    def test_extracts_user_id_from_dict_input(self, mock_zentinelle_client):
        mock_zentinelle_client.evaluate.return_value = FakeEvaluateResult(allowed=True)
        from zentinelle_langchain import ZentinelleGuardrail
        guard = ZentinelleGuardrail(mock_zentinelle_client)

        guard.invoke({'user_id': 'user-123', 'query': 'hello'})

        _, kwargs = mock_zentinelle_client.evaluate.call_args
        assert kwargs['user_id'] == 'user-123'


class TestOutputGuardrail:
    def test_allows_clean_output(self, mock_zentinelle_client):
        mock_zentinelle_client.evaluate.return_value = FakeEvaluateResult(allowed=True)
        from zentinelle_langchain import ZentinelleGuardrail
        guard = ZentinelleGuardrail(mock_zentinelle_client)
        output_guard = guard.output()

        result = output_guard.invoke("Clean response")

        assert result == "Clean response"

    def test_blocks_unsafe_output(self, mock_zentinelle_client):
        mock_zentinelle_client.evaluate.return_value = FakeEvaluateResult(
            allowed=False, reason='Contains secrets'
        )
        from zentinelle_langchain import ZentinelleGuardrail
        from zentinelle_langchain.guardrail import PolicyViolationError
        guard = ZentinelleGuardrail(mock_zentinelle_client)
        output_guard = guard.output()

        with pytest.raises(PolicyViolationError, match='Contains secrets'):
            output_guard.invoke("API key: sk-abc123")


class TestToolWrapper:
    def test_allows_tool_execution(self, mock_zentinelle_client):
        mock_zentinelle_client.evaluate.return_value = FakeEvaluateResult(allowed=True)
        from zentinelle_langchain import ZentinelleToolWrapper

        tool = MagicMock()
        tool.name = 'web_search'
        tool._run = MagicMock(return_value='search results')

        wrapper = ZentinelleToolWrapper(mock_zentinelle_client)
        wrapped = wrapper.wrap(tool)

        result = wrapped._run('test query')

        assert result == 'search results'
        mock_zentinelle_client.evaluate.assert_called_once()
        mock_zentinelle_client.emit_tool_call.assert_called_once()

    def test_blocks_denied_tool(self, mock_zentinelle_client):
        mock_zentinelle_client.evaluate.return_value = FakeEvaluateResult(
            allowed=False, reason='Tool web_search is denied'
        )
        from zentinelle_langchain import ZentinelleToolWrapper
        from zentinelle_langchain.guardrail import PolicyViolationError

        tool = MagicMock()
        tool.name = 'web_search'
        original_run = MagicMock()
        tool._run = original_run

        wrapper = ZentinelleToolWrapper(mock_zentinelle_client)
        wrapped = wrapper.wrap(tool)

        with pytest.raises(PolicyViolationError, match='denied'):
            wrapped._run('query')

        original_run.assert_not_called()

    def test_wrap_all(self, mock_zentinelle_client):
        mock_zentinelle_client.evaluate.return_value = FakeEvaluateResult(allowed=True)
        from zentinelle_langchain import ZentinelleToolWrapper

        tools = [MagicMock() for _ in range(3)]
        for i, t in enumerate(tools):
            t.name = f'tool_{i}'
            t._run = MagicMock(return_value=f'result_{i}')

        wrapper = ZentinelleToolWrapper(mock_zentinelle_client)
        wrapped = wrapper.wrap_all(tools)

        assert len(wrapped) == 3
