"""Audit for DSPy runs. Audit only, and unavoidably so.

`BaseCallback` handlers are dispatched inside a `try/except` that logs and
continues, so nothing here can refuse anything: raising from `on_lm_start`
prints a warning and the model is called regardless. Enforcement lives in
`governed.py`.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from dspy.utils.callback import BaseCallback

logger = logging.getLogger(__name__)

AGENT_TYPE = "dspy"


class ZentinelleCallback(BaseCallback):
    """Records LM and tool calls as Zentinelle events.

        dspy.configure(callbacks=[ZentinelleCallback(client)])

    Registering this does not govern a program. It reports one.
    """

    def __init__(self, client: Any, user_id: Optional[str] = None):
        self.client = client
        self.user_id = user_id

    def on_lm_end(self, call_id, outputs, exception=None):
        self._emit("lm_call", call_id, exception)

    def on_tool_end(self, call_id, outputs, exception=None):
        self._emit("tool_call_observed", call_id, exception)

    def on_module_end(self, call_id, outputs, exception=None):
        self._emit("module_call", call_id, exception)

    def _emit(self, event_type: str, call_id, exception) -> None:
        payload = {"harness": AGENT_TYPE, "call_id": call_id}
        if exception is not None:
            payload["error"] = str(exception)
        try:
            self.client.emit(event_type, payload, category="audit",
                             user_id=self.user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record %s: %s", event_type, exc)
