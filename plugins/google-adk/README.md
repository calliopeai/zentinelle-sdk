# zentinelle-google-adk

Zentinelle governance for the [Google Agent Development Kit](https://github.com/google/adk-python).

`agent_type`: `google_adk`

## What it covers

| Callback | Covers | Enforcing |
|---|---|---|
| `before_model_callback` | model requests | yes, before the model is called |
| `after_model_callback` | token usage | records |
| `before_tool_callback` | tool calls | yes, before the tool runs |
| `after_tool_callback` | tool audit | records |
| `gateway_model()` | routes calls through a Zentinelle gateway | at the gateway |

## Install

```bash
pip install zentinelle-google-adk
```

## Use

```python
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from zentinelle import ZentinelleClient
from zentinelle_google_adk import ZentinellePlugin

client = ZentinelleClient(api_key="sk_agent_...", agent_type="google_adk")

runner = Runner(
    agent=LlmAgent(name="assistant", model="gemini-2.0-flash"),
    plugins=[ZentinellePlugin(client)],
    app_name="my-app",
    session_service=...,
)
```

## A plugin, not per-agent callbacks

ADK offers both. This is registered as a plugin for two reasons: a plugin
covers every agent the runner drives, including sub-agents a multi-agent app
creates at runtime, so governance cannot be sidestepped by adding an agent; and
ADK gives plugin callbacks precedence over an agent's own, so an agent cannot
register a callback that pre-empts this one.

## Denials are returned, not raised

That is ADK's contract, not a choice made here: a `before_*` callback returning
non-`None` short-circuits what follows, and the returned value becomes the
result. A refused request comes back as an `LlmResponse` saying why; a refused
tool call comes back as an error dict. Raising instead would abort the runner
rather than produce a refusal the caller can read.

## Routing through the gateway

A native Gemini model has no base-URL override, so `gateway_model()` builds a
`LiteLlm` model instead. `api_base` and `api_key` are litellm's parameter
names, forwarded through ADK rather than defined by it.

Checks fail closed; pass `fail_open=True` to prefer availability.
