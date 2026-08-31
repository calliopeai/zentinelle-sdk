# zentinelle-pydantic-ai

Zentinelle governance for [Pydantic AI](https://github.com/pydantic/pydantic-ai).

`agent_type`: `pydantic_ai`

## What it covers

| Piece | Covers | Enforcing |
|---|---|---|
| `ZentinelleCapability` | model requests | yes, before the model is called |
| `ZentinelleCapability` | tool calls | yes, before the tool runs |
| `ZentinelleCapability` | token usage, tool audit | records |
| `gateway_model()` | routes calls through a Zentinelle gateway | at the gateway |

Pydantic AI has the cleanest enforcement surface of the harnesses covered here.
Its capability hooks are awaited on the path to the thing they precede, so
nothing needs wrapping, subclassing or patching.

## Install

```bash
pip install zentinelle-pydantic-ai
```

## Use

```python
from pydantic_ai import Agent
from zentinelle import ZentinelleClient
from zentinelle_pydantic_ai import ZentinelleCapability, gateway_model

client = ZentinelleClient(api_key="sk_agent_...", agent_type="pydantic_ai")

agent = Agent(
    gateway_model("gpt-5", gateway_url="https://zentinelle-gateway.internal"),
    capabilities=[ZentinelleCapability(client)],
)

result = await agent.run("...")
```

## Denials

By default a denial raises `PolicyViolationError`, which stops the run.

Pydantic AI's own mechanism is `SkipModelRequest` / `SkipToolExecution`, which
substitute a result and let the agent continue. That is the right shape for a
fallback and the wrong one for a refusal: handing the denial back as a tool
result lets the model decide what to do about its own governance, and in
practice it tries another route to the same action. Pass
`on_denial="substitute"` if a soft refusal is what you want.

## Other defaults

**Checks fail closed.** If the control plane cannot be reached, the request or
tool call is refused. `fail_open=True` prefers availability.

**The client is called off the event loop.** `ZentinelleClient` is synchronous
`requests`; awaiting it directly would block the loop the agent runs on, and
with it every other request in the process.

## Use both the capability and the gateway

They are independent. The capability cannot see a call made by some other
client in the same process; the gateway cannot refuse a tool call, because a
tool call never reaches it.
