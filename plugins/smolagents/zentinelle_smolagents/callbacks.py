"""Audit for smolagents runs. Audit only.

`step_callbacks` fire from `_finalize_step`, after the model has answered and
any tool has run. Nothing here can refuse anything; enforcement is in
`governed.py`.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

AGENT_TYPE = "smolagents"


class ZentinelleStepCallback:
    """Records each completed step as a Zentinelle event.

        agent = CodeAgent(..., step_callbacks=[ZentinelleStepCallback(client)])

    The callback takes `(memory_step, **kwargs)`; smolagents passes `agent=`
    only to callbacks that declare more than one parameter, which `__call__`
    below does.
    """

    def __init__(self, client: Any, user_id: Optional[str] = None):
        self.client = client
        self.user_id = user_id

    def __call__(self, memory_step, **kwargs) -> None:
        payload = {
            "harness": AGENT_TYPE,
            "step_type": type(memory_step).__name__,
            "step_number": getattr(memory_step, "step_number", None),
        }

        usage = getattr(memory_step, "token_usage", None)
        if usage is not None:
            payload["input_tokens"] = getattr(usage, "input_tokens", None)
            payload["output_tokens"] = getattr(usage, "output_tokens", None)

        agent = kwargs.get("agent")
        if agent is not None:
            payload["agent"] = getattr(agent, "name", None) or type(agent).__name__

        error = getattr(memory_step, "error", None)
        if error is not None:
            payload["error"] = str(error)

        try:
            self.client.emit(
                "agent_step",
                {k: v for k, v in payload.items() if v is not None},
                category="audit",
                user_id=self.user_id,
            )
        except Exception as exc:  # noqa: BLE001
            # A callback that raised would take the agent down mid-run, and
            # this one only exists to write things down.
            logger.warning("Could not record step: %s", exc)
