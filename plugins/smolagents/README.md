# zentinelle-smolagents

Zentinelle governance for [smolagents](https://github.com/huggingface/smolagents) (Hugging Face).

`agent_type`: `smolagents`

## What it covers

| Piece | Covers | Enforcing |
|---|---|---|
| `ZentinelleModel` | model requests, token usage | yes, before the provider is called |
| `govern_tools()` / `governed_tool()` | tool calls | yes, a denied tool does not run |
| `ZentinelleStepCallback` | completed steps | records only |
| `gateway_model()` | routes calls through a Zentinelle gateway | at the gateway |

## Install

```bash
pip install zentinelle-smolagents
```

## Use

```python
from smolagents import CodeAgent
from zentinelle import ZentinelleClient
from zentinelle_smolagents import ZentinelleModel, gateway_model, govern_tools

client = ZentinelleClient(api_key="sk_agent_...", agent_type="smolagents")

agent = CodeAgent(
    model=ZentinelleModel(
        gateway_model("gpt-5", gateway_url="https://zentinelle-gateway.internal"),
        client,
    ),
    tools=govern_tools([my_tool], client),
)
```

## Why wrapping, and why both wrappers

smolagents has no pre-execution hook. `step_callbacks` fires from
`_finalize_step`, after the model has answered and the tool has run, so it can
record a run but cannot change one; `final_answer_checks` gates only the final
answer. Enforcement therefore has to wrap the things being governed.

Both wrappers are needed, and this is the important part for `CodeAgent`. A
`ToolCallingAgent` routes every call through `execute_tool_call`, so in
principle one override would cover it. A `CodeAgent` does not call tools at
all: the model writes Python, and the executor runs it with the tool objects
in its namespace. Nothing sits between the model and the tool except the tool,
which is why governance goes on the tool itself.

`governed_tool` wraps `forward`, not `__call__`. Assigning `__call__` on an
instance does nothing useful, because Python looks up dunder methods on the
type — the tool would still run ungoverned while appearing wrapped. Wrapping
`forward` also keeps `Tool.__call__`'s input sanitisation intact.

## Defaults

A denial raises `PolicyViolationError`. Checks fail closed; pass
`fail_open=True` to prefer availability.
