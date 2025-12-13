"""
Zentinelle callback handler for CrewAI.
"""

import time
from typing import Any, Optional

from zentinelle import ZentinelleClient
from zentinelle.types import ModelUsage


class ZentinelleCrewCallback:
    """
    Callback handler for tracking CrewAI execution in Zentinelle.

    Tracks:
    - Task starts and completions
    - Tool calls
    - Agent activities
    - LLM usage
    - Errors

    Example:
        client = ZentinelleClient(api_key="...", agent_id="...")
        callback = ZentinelleCrewCallback(client)

        crew = Crew(
            agents=[...],
            tasks=[...],
            callbacks=[callback]
        )
    """

    def __init__(
        self,
        client: ZentinelleClient,
        track_prompts: bool = False,
        track_outputs: bool = True,
        max_output_length: int = 500,
    ):
        """
        Initialize the callback handler.

        Args:
            client: Zentinelle client instance
            track_prompts: Whether to track prompt content (may contain sensitive data)
            track_outputs: Whether to track output content
            max_output_length: Maximum length of tracked outputs
        """
        self._client = client
        self._track_prompts = track_prompts
        self._track_outputs = track_outputs
        self._max_output_length = max_output_length

        self._task_start_times: dict[str, float] = {}
        self._agent_start_times: dict[str, float] = {}

    def on_task_start(self, task: Any) -> None:
        """Called when a task starts."""
        task_id = str(id(task))
        self._task_start_times[task_id] = time.time()

        self._client.emit(
            category="task_execution",
            action="task_start",
            success=True,
            metadata={
                "task_id": task_id,
                "description": getattr(task, "description", "")[:200],
            },
        )

    def on_task_end(self, task: Any, output: Any) -> None:
        """Called when a task completes."""
        task_id = str(id(task))
        duration_ms = self._get_duration_ms(self._task_start_times.pop(task_id, None))

        metadata: dict[str, Any] = {
            "task_id": task_id,
            "duration_ms": duration_ms,
        }

        if self._track_outputs and output:
            metadata["output_preview"] = str(output)[: self._max_output_length]
            metadata["output_length"] = len(str(output))

        self._client.emit(
            category="task_execution",
            action="task_end",
            success=True,
            metadata=metadata,
        )

    def on_task_error(self, task: Any, error: Exception) -> None:
        """Called when a task fails."""
        task_id = str(id(task))
        duration_ms = self._get_duration_ms(self._task_start_times.pop(task_id, None))

        self._client.emit(
            category="task_execution",
            action="task_error",
            success=False,
            metadata={
                "task_id": task_id,
                "duration_ms": duration_ms,
                "error": str(error)[:500],
                "error_type": type(error).__name__,
            },
        )

    def on_agent_start(self, agent: Any, task: Any) -> None:
        """Called when an agent starts working on a task."""
        agent_id = str(id(agent))
        self._agent_start_times[agent_id] = time.time()

        self._client.emit(
            category="task_execution",
            action="agent_start",
            success=True,
            metadata={
                "agent_id": agent_id,
                "role": getattr(agent, "role", "unknown"),
                "task_description": getattr(task, "description", "")[:200],
            },
        )

    def on_agent_end(self, agent: Any, output: Any) -> None:
        """Called when an agent finishes working."""
        agent_id = str(id(agent))
        duration_ms = self._get_duration_ms(self._agent_start_times.pop(agent_id, None))

        metadata: dict[str, Any] = {
            "agent_id": agent_id,
            "role": getattr(agent, "role", "unknown"),
            "duration_ms": duration_ms,
        }

        if self._track_outputs and output:
            metadata["output_preview"] = str(output)[: self._max_output_length]

        self._client.emit(
            category="task_execution",
            action="agent_end",
            success=True,
            metadata=metadata,
        )

    def on_tool_start(self, tool_name: str, tool_input: Any) -> None:
        """Called when a tool is invoked."""
        metadata: dict[str, Any] = {"tool": tool_name}

        if self._track_prompts:
            metadata["input_preview"] = str(tool_input)[: self._max_output_length]

        self._client.emit(
            category="tool_call",
            action=f"tool_start_{tool_name}",
            success=True,
            metadata=metadata,
        )

    def on_tool_end(self, tool_name: str, tool_output: Any) -> None:
        """Called when a tool completes."""
        metadata: dict[str, Any] = {"tool": tool_name}

        if self._track_outputs:
            metadata["output_preview"] = str(tool_output)[: self._max_output_length]

        self._client.emit(
            category="tool_call",
            action=tool_name,
            success=True,
            metadata=metadata,
        )

    def on_tool_error(self, tool_name: str, error: Exception) -> None:
        """Called when a tool fails."""
        self._client.emit(
            category="tool_call",
            action=tool_name,
            success=False,
            metadata={
                "error": str(error)[:500],
                "error_type": type(error).__name__,
            },
        )

    def on_llm_start(self, model: str, prompts: list[str]) -> None:
        """Called when an LLM request starts."""
        metadata: dict[str, Any] = {
            "model": model,
            "prompt_count": len(prompts),
        }

        if self._track_prompts:
            total_chars = sum(len(p) for p in prompts)
            metadata["total_prompt_chars"] = total_chars

        self._client.emit(
            category="model_request",
            action=f"llm_start_{model}",
            success=True,
            metadata=metadata,
        )

    def on_llm_end(
        self,
        model: str,
        response: Any,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost: Optional[float] = None,
    ) -> None:
        """Called when an LLM request completes."""
        model_usage = None
        if input_tokens or output_tokens:
            model_usage = ModelUsage(
                model=model,
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
                cost=cost,
            )

        metadata: dict[str, Any] = {"model": model}
        if self._track_outputs and response:
            metadata["response_preview"] = str(response)[: self._max_output_length]

        self._client.emit(
            category="model_request",
            action=model,
            success=True,
            model_usage=model_usage,
            metadata=metadata,
        )

    def on_llm_error(self, model: str, error: Exception) -> None:
        """Called when an LLM request fails."""
        self._client.emit(
            category="model_request",
            action=model,
            success=False,
            metadata={
                "error": str(error)[:500],
                "error_type": type(error).__name__,
            },
        )

    def on_chain_start(self, chain_name: str) -> None:
        """Called when a chain/process starts."""
        self._client.emit(
            category="task_execution",
            action=f"chain_start_{chain_name}",
            success=True,
            metadata={"chain": chain_name},
        )

    def on_chain_end(self, chain_name: str, output: Any) -> None:
        """Called when a chain/process ends."""
        metadata: dict[str, Any] = {"chain": chain_name}
        if self._track_outputs and output:
            metadata["output_preview"] = str(output)[: self._max_output_length]

        self._client.emit(
            category="task_execution",
            action=f"chain_end_{chain_name}",
            success=True,
            metadata=metadata,
        )

    def _get_duration_ms(self, start_time: Optional[float]) -> Optional[int]:
        """Calculate duration in milliseconds from start time."""
        if start_time is None:
            return None
        return int((time.time() - start_time) * 1000)
