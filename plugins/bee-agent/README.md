# zentinelle-bee-agent

Zentinelle governance for the [BeeAI Framework](https://github.com/i-am-bee/beeai-framework)
(IBM's Bee Agent Framework, under Linux Foundation governance).

`agent_type`: `bee_agent`

## What it covers

| Piece | Covers | Enforcing |
|---|---|---|
| `guard.attach_model()` | model requests | yes, before the provider is called |
| `guard.attach_tool()` | tool invocations | yes, before the tool body runs |
| `guard.attach_agent()` | both, for a whole agent | yes |
| token usage | recorded from the `success` event | records |
| `gateway_model()` | routes calls through a Zentinelle gateway | at the gateway |

## Install

```bash
pip install zentinelle-bee-agent
```

## Use

```python
from beeai_framework.agents.tool_calling import ToolCallingAgent
from zentinelle import ZentinelleClient
from zentinelle_bee_agent import ZentinelleGuard, gateway_model

client = ZentinelleClient(api_key="sk_agent_...", agent_type="bee_agent")
guard = ZentinelleGuard(client)

llm = gateway_model("gpt-5", gateway_url="https://zentinelle-gateway.internal")
agent = ToolCallingAgent(llm=llm, tools=tools, memory=memory)

guard.attach_agent(agent)   # covers the model and every tool under this agent
```

Or subscribe individually with `attach_model(llm)` and `attach_tool(tool)`.

## Why the emitter actually works here

Most agent frameworks' event systems are notification-only: they catch what a
listener raises and carry on. BeeAI's does not. `Emitter._invoke` wraps a
listener's exception as an `EmitterError` and re-raises it inside an
`asyncio.TaskGroup`, so it propagates out of `emit()`.

And the `"start"` event fires before the work: ahead of `Tool._run` for a tool,
and ahead of the retryable that calls the provider for a chat model. So a
listener that raises on `"start"` genuinely stops the call.

`attach_agent` matters for `ReActAgent` and `ToolCallingAgent`, which take no
middleware constructor argument at all. Child emitters pipe into the agent's,
so one subscription there still sees the model and tool events for the run.

## Defaults

A denial raises `PolicyViolationError`. Checks fail closed; pass
`fail_open=True` to prefer availability.
