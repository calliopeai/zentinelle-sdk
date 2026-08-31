# zentinelle-dspy

Zentinelle governance for [DSPy](https://github.com/stanfordnlp/dspy) (Stanford).

`agent_type`: `dspy`

## What it covers

| Piece | Covers | Enforcing |
|---|---|---|
| `ZentinelleLM` | model requests, token usage | yes, before the provider is called |
| `govern_tools()` / `governed_tool()` | tool calls | yes, a denied tool does not run |
| `ZentinelleCallback` | LM, tool and module calls | records only |
| `gateway_lm_kwargs()` | routes calls through a Zentinelle gateway | at the gateway |

## Install

```bash
pip install zentinelle-dspy
```

## Use

```python
import dspy
from zentinelle import ZentinelleClient
from zentinelle_dspy import ZentinelleLM, gateway_lm_kwargs, govern_tools

client = ZentinelleClient(api_key="sk_agent_...", agent_type="dspy")

dspy.configure(lm=ZentinelleLM(
    client,
    "openai/gpt-5",
    **gateway_lm_kwargs(gateway_url="https://zentinelle-gateway.internal"),
))

tools = govern_tools([dspy.Tool(my_function)], client)
```

## Why not a callback

DSPy has `BaseCallback`, with `on_lm_start` and `on_tool_start`. They look like
the integration point and they are not one.

DSPy's dispatcher wraps every callback invocation in its own `try/except`,
logs the exception, and then calls the wrapped function anyway:

```python
try:
    _get_on_start_handler(callback, instance, fn)(...)
except Exception as e:
    logger.warning(f"Error when calling callback {callback}: {e}")
```

So a governance callback that raised would print a warning and let the request
through — a plugin that looked like it was enforcing while enforcing nothing.
That is why `ZentinelleLM` subclasses `dspy.LM` and checks in `forward`, and
why `governed_tool` wraps a tool's `func` rather than listening for
`on_tool_start`.

`ZentinelleCallback` is provided for audit and is audit only. It is built on
the same dispatcher, so it cannot refuse anything, and it says so.

## Defaults

A denial raises `PolicyViolationError`. Checks fail closed; pass
`fail_open=True` to prefer availability.

DSPy has no `api_base` parameter of its own — `LM` forwards unrecognised
keyword arguments to litellm, and `api_base` / `api_key` are litellm's names.
`gateway_lm_kwargs()` returns them.
