# zentinelle-mistral-agents

Zentinelle governance for the [Mistral Agents API](https://github.com/mistralai/client-python).

`agent_type`: `mistral_agents`

## Read this first

Mistral's Agents API is a **server-side runtime**. The agent loop, and every
server-side tool — web search, code interpreter, connectors, document library,
image generation — execute on Mistral's infrastructure between your request and
your response.

| Capability | Status |
|---|---|
| refuse a request before it is sent | **enforced** |
| token usage | recorded, from the response |
| block a server-side tool call | **not possible** — the client never sees one |
| block a client-side function tool | not needed — you execute it yourself |

There is no `BeforeToolCallHook` anywhere in the SDK; its only hook types are
`sdk_init`, `before_request`, `after_success` and `after_error`, all at the raw
HTTP layer. For client-side function tools, Mistral returns the tool call and
you decide whether to run it, so there is nothing to intercept.

## Install

```bash
pip install zentinelle-mistral-agents
```

## Use

```python
from mistralai.client import Mistral
from zentinelle import ZentinelleClient
from zentinelle_mistral_agents import GovernedMistral

client = ZentinelleClient(api_key="sk_agent_...", agent_type="mistral_agents")
mistral = GovernedMistral(Mistral(api_key="..."), client)

response = mistral.chat_complete(model="mistral-large-latest", messages=[...])
conversation = mistral.conversation_start(agent_id="...", inputs=[...])
```

Attribute access falls through to the wrapped client, so the rest of the SDK
still works — and that is the caveat. `mistral.chat.complete(...)` reaches the
ungoverned path, because there is no interceptor underneath. Use the methods
above.

## Covering every request

`install_request_hook(client, zentinelle_client)` checks every request that
client makes, including calls made by code you did not write.

It is **unsupported**, and deliberately labelled so. Mistral's SDK builds its
hook registry inside `Mistral.__init__` and offers no way to add to it; the
registry lives on an undeclared private attribute, and this reaches in there.
The mechanism itself is real — a `BeforeRequestHook` that returns an exception
aborts the request before the HTTP send — but the access path can break on any
SDK upgrade. It raises immediately if the internals have moved, rather than
returning quietly and leaving a deployment believing it is governed.

Prefer `GovernedMistral` wherever the call sites are yours to change.

## Routing through a gateway

```python
from zentinelle_mistral_agents import gateway_server_url

Mistral(api_key="...", server_url=gateway_server_url("https://gateway.internal"))
```

Note this does *not* reuse the shared `gateway_base_url` helper: that appends
`/v1` for OpenAI-compatible clients, and the Mistral SDK adds its own `/v1` to
every path, which would give `/v1/v1/...`.

## Defaults

A denial raises `PolicyViolationError`. Checks fail closed; pass
`fail_open=True` to prefer availability.

## Import path changed in mistralai 2.x

`mistralai` became a namespace package in 2.x and the client moved:

```python
from mistralai.client import Mistral   # 2.x
from mistralai import Mistral          # 1.x
```

Verified against 2.9.4. The plugin itself does not import the SDK — it wraps
whatever client you hand it — so both versions work; only the import in your
own code differs.
