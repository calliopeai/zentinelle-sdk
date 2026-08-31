"""Zentinelle governance for the Mistral Agents API.

Mistral's Agents API is a server-side runtime: the agent loop, and any
server-side tool (web search, code interpreter, connectors), execute on
Mistral's infrastructure between your request and your response. So the honest
summary is:

- **enforced**: whether a request is sent at all
- **recorded**: token usage, from the response
- **not possible**: blocking an individual server-side tool call, because the
  client never sees one

Two ways to enforce, and they differ in how much they cover.

`GovernedMistral` wraps the call sites and checks before sending. Supported,
stable, and covers what you call through it.

`install_request_hook` reaches into the SDK's private hook registry so that
*every* request through that client is checked, including ones made by code you
did not write. It works — the SDK's `BeforeRequestHook` genuinely aborts a
request when it returns an exception, before the HTTP send — but the registry
is a private attribute with no public accessor, so it is unsupported and can
break on an SDK upgrade. It is opt-in for that reason, and it fails loudly
rather than silently when the internals move.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

AGENT_TYPE = "mistral_agents"

_CONTENT_LIMIT = 4000


class PolicyViolationError(Exception):
    """A request was refused by policy before being sent."""

    def __init__(self, message: str, result: Any = None):
        super().__init__(message)
        self.result = result


def _summarise(value: Any, limit: int = _CONTENT_LIMIT) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    parts = []
    for message in list(value)[-4:] if isinstance(value, (list, tuple)) else []:
        content = (
            message.get("content")
            if isinstance(message, dict)
            else getattr(message, "content", None)
        )
        if isinstance(content, str):
            parts.append(content)
        elif content is not None:
            parts.append(str(content))
    if parts:
        return "\n".join(parts)[:limit]
    return str(value)[:limit]


class GovernedMistral:
    """A Mistral client whose requests are checked before they are sent.

        from mistralai import Mistral
        from zentinelle_mistral_agents import GovernedMistral

        client = GovernedMistral(Mistral(api_key="..."), zentinelle_client)
        response = client.chat_complete(model="mistral-large-latest",
                                        messages=[...])

    Attribute access falls through to the wrapped client, so the rest of the
    SDK still works. That is also the caveat: reaching past these methods, for
    example `client.chat.complete(...)`, is the ungoverned path. Use
    `install_request_hook` if you need every call covered.
    """

    def __init__(
        self,
        client: Any,
        zentinelle_client: Any,
        user_id: Optional[str] = None,
        evaluate_requests: bool = True,
        track_token_usage: bool = True,
        fail_open: bool = False,
    ):
        self._client = client
        self.zentinelle = zentinelle_client
        self.user_id = user_id
        self.evaluate_requests = evaluate_requests
        self.track_token_usage = track_token_usage
        self.fail_open = fail_open

    def __getattr__(self, name):
        return getattr(self.__dict__["_client"], name)

    # -- governed call sites ----------------------------------------------

    def chat_complete(self, **kwargs):
        """`client.chat.complete`, with a policy check in front."""
        if self.evaluate_requests:
            self._check(kwargs.get("messages"), kwargs.get("model"))
        response = self._client.chat.complete(**kwargs)
        if self.track_token_usage:
            self._track(response, kwargs.get("model"))
        return response

    def conversation_start(self, **kwargs):
        """`client.beta.conversations.start`, with a policy check in front."""
        if self.evaluate_requests:
            self._check(kwargs.get("inputs"), kwargs.get("model"))
        response = self._client.beta.conversations.start(**kwargs)
        if self.track_token_usage:
            self._track(response, kwargs.get("model"))
        return response

    def conversation_append(self, **kwargs):
        """`client.beta.conversations.append`, with a policy check in front."""
        if self.evaluate_requests:
            self._check(kwargs.get("inputs"), None)
        response = self._client.beta.conversations.append(**kwargs)
        if self.track_token_usage:
            self._track(response, None)
        return response

    # -- internals --------------------------------------------------------

    def _check(self, content, model) -> None:
        try:
            result = self.zentinelle.evaluate(
                "model_request",
                self.user_id,
                {
                    "direction": "input",
                    "harness": AGENT_TYPE,
                    "model": model or "unknown",
                    "content": _summarise(content),
                },
            )
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Zentinelle check failed, allowing: %s", exc)
                return
            raise PolicyViolationError(
                f"Zentinelle policy check failed and fail_open is off: {exc}"
            ) from exc

        if not result.allowed:
            raise PolicyViolationError(
                f"Request refused by policy: {result.reason or 'no reason given'}",
                result,
            )

    def _track(self, response, model) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        try:
            from zentinelle import ModelUsage

            self.zentinelle.track_usage(
                ModelUsage(
                    provider="mistral",
                    model=model or "unknown",
                    input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record model usage: %s", exc)


class _ZentinelleBeforeRequestHook:
    """Refuses a request by returning an exception.

    Mistral's hook contract is unusual: a `before_request` hook *returns* an
    exception rather than raising one, and the SDK raises it before sending.
    Returning anything else is taken as the request to send.
    """

    def __init__(self, zentinelle_client, user_id=None, fail_open=False):
        self.zentinelle = zentinelle_client
        self.user_id = user_id
        self.fail_open = fail_open

    def before_request(self, hook_ctx, request):
        try:
            result = self.zentinelle.evaluate(
                "model_request",
                self.user_id,
                {
                    "direction": "input",
                    "harness": AGENT_TYPE,
                    "operation": getattr(hook_ctx, "operation_id", None) or "unknown",
                },
            )
        except Exception as exc:  # noqa: BLE001
            if self.fail_open:
                logger.warning("Zentinelle check failed, allowing: %s", exc)
                return request
            return PolicyViolationError(
                f"Zentinelle policy check failed and fail_open is off: {exc}"
            )

        if not result.allowed:
            return PolicyViolationError(
                f"Request refused by policy: {result.reason or 'no reason given'}",
                result,
            )
        return request


def install_request_hook(
    client: Any,
    zentinelle_client: Any,
    user_id: Optional[str] = None,
    fail_open: bool = False,
):
    """Check every request the client makes, including ones you did not write.

    **Unsupported.** Mistral's SDK builds its hook registry inside
    ``Mistral.__init__`` and exposes no way to add to it; the registry lives on
    an undeclared private attribute. This reaches in there. It works today and
    can stop working on any SDK upgrade.

    It raises immediately if the internals have moved, rather than returning
    quietly and leaving a deployment believing it is governed when it is not.
    Prefer `GovernedMistral` where the call sites are yours to change.
    """
    configuration = getattr(client, "sdk_configuration", None)
    hooks = getattr(configuration, "__dict__", {}).get("_hooks") if configuration else None

    if hooks is None or not hasattr(hooks, "register_before_request_hook"):
        raise RuntimeError(
            "Could not reach the Mistral SDK's hook registry "
            "(sdk_configuration.__dict__['_hooks']). This is a private "
            "attribute and the SDK has changed. Use GovernedMistral instead, "
            "which relies only on the public API."
        )

    hooks.register_before_request_hook(
        _ZentinelleBeforeRequestHook(zentinelle_client, user_id, fail_open)
    )
    return client
