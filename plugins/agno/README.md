# zentinelle-agno

Zentinelle governance for [Agno](https://github.com/agno-agi/agno).

`agent_type`: `agno`

## What it covers

| Piece | Covers | Enforcing |
|---|---|---|
| `guard.pre_hook` | run input | yes, before the model is called |
| `guard.post_hook` | run output, token usage | yes on output, records usage |
| `guard.tool_hook` | tool calls | yes, a denied tool does not run |
| `gateway_model()` | routes calls through a Zentinelle gateway | at the gateway |

## Install

```bash
pip install zentinelle-agno
```

## Use

```python
from agno.agent import Agent
from zentinelle import ZentinelleClient
from zentinelle_agno import ZentinelleGuard, gateway_model

client = ZentinelleClient(api_key="sk_agent_...", agent_type="agno")
guard = ZentinelleGuard(client)

agent = Agent(
    model=gateway_model("gpt-5", gateway_url="https://zentinelle-gateway.internal"),
    pre_hooks=[guard.pre_hook],
    post_hooks=[guard.post_hook],
    tool_hooks=[guard.tool_hook],
)
```

## Why the hooks raise Agno's own exceptions

Agno catches and logs any exception a pre- or post-hook raises, **except**
`InputCheckError` and `OutputCheckError`. Those two are re-raised and stop the
run. So a governance plugin that raised anything else would appear to be
enforcing while the run carried on ungoverned, including when the control
plane is unreachable and the check itself fails. That is why the fail-closed
path raises the check error rather than a plugin-specific one.

Tool hooks are middleware: Agno hands the hook the function it wraps, so a
refusal is simply not calling it. That one raises `PolicyViolationError`,
which propagates.

## Hook parameter names are load-bearing

Agno inspects each hook's signature and passes only the arguments it declares
by name. `pre_hook(run_input)`, `post_hook(run_output)` and
`tool_hook(function_name, func, arguments)` use the names Agno looks for.
Renaming a parameter does not error; the value simply never arrives.

## Defaults

Checks fail closed. `ZentinelleGuard(client, fail_open=True)` prefers
availability.
