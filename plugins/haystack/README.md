# zentinelle-haystack

Zentinelle governance for [Haystack](https://github.com/deepset-ai/haystack) (deepset).

`agent_type`: `haystack`

## What it covers

Haystack has two shapes and they need different things.

| Piece | For | Covers | Enforcing |
|---|---|---|---|
| `ZentinelleChatGenerator` | any `Pipeline` | model requests and replies, token usage | yes, before the generator runs |
| `ZentinelleToolHook` | `components.agents.Agent` | tool calls | yes, before any tool runs |
| `gateway_generator()` | either | routes calls through a Zentinelle gateway | at the gateway |

A plain `Pipeline` has no hook points at all: it runs components, and a
component's `run` is called directly. So the interception point is a component
of our own that wraps the real generator. Drop it where the generator went and
the connections are unchanged.

## Install

```bash
pip install zentinelle-haystack
```

## Use

```python
from haystack import Pipeline
from zentinelle import ZentinelleClient
from zentinelle_haystack import ZentinelleChatGenerator, gateway_generator

client = ZentinelleClient(api_key="sk_agent_...", agent_type="haystack")

pipeline = Pipeline()
pipeline.add_component(
    "llm",
    ZentinelleChatGenerator(
        gateway_generator("gpt-5-mini", gateway_url="https://zentinelle-gateway.internal"),
        client,
    ),
)
```

With an Agent, add the tool hook:

```python
from haystack.components.agents import Agent
from zentinelle_haystack import ZentinelleToolHook

agent = Agent(
    chat_generator=gateway_generator("gpt-5-mini"),
    tools=[...],
    hooks={"before_tool": [ZentinelleToolHook(client)]},
)
```

## Denials

The hook raises, which aborts the run: Haystack runs hooks with no exception
handling around them.

Haystack's own `ConfirmationHook` instead rejects by rewriting the message
history, returning the refusal to the model as a tool result. That is the right
shape for a human declining an action and the wrong one for a policy denial,
because it lets the agent try another route to the same thing.

## Notes

`ToolInvoker` does not exist in haystack-ai 3.x. Tools run inside the `Agent`,
which is why tool governance here is a hook rather than a pipeline component.

The generator wrapper takes any generator with a compatible `run`, not only
OpenAI's. Token usage is read from `reply.meta["usage"]`, whose keys are the
provider's own.

Checks fail closed; pass `fail_open=True` to prefer availability.
