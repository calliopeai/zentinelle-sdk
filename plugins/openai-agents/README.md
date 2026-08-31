# zentinelle-openai-agents

Zentinelle governance for agents built on the [OpenAI Agents SDK](https://github.com/openai/openai-agents-python).

`agent_type`: `openai_agents`

## What it covers

The Agents SDK has no single interception point, so this plugin uses four,
each covering something the others cannot see.

| Piece | Covers | Enforcing? |
|---|---|---|
| `configure()` | every LLM call the SDK makes, including the ones it makes on its own account | yes, at the gateway |
| `zentinelle_input_guardrail` | what goes into a run | yes, trips before the model is called |
| `zentinelle_output_guardrail` | the agent's final output | yes, trips before the caller sees it |
| `ZentinelleRunHooks` | tool calls, handoffs, token usage | yes, a denied tool does not run |
| `ZentinelleTracingProcessor` | the trace of the run | no, records only |

Use the gateway *and* the hooks. A gateway cannot refuse a tool call, because a
tool call is not an LLM request; hooks cannot see a request the SDK issues for
itself, such as a structured-output retry.

## Install

```bash
pip install zentinelle-openai-agents
```

## Use

```python
from agents import Agent, Runner
from zentinelle import ZentinelleClient
from zentinelle_openai_agents import (
    ZentinelleRunHooks,
    configure,
    zentinelle_input_guardrail,
    zentinelle_output_guardrail,
)

client = ZentinelleClient(api_key="sk_agent_...", agent_type="openai_agents")

configure(
    gateway_url="https://zentinelle-gateway.internal",
    zentinelle_client=client,
)

agent = Agent(
    name="assistant",
    instructions="Help the user.",
    input_guardrails=[zentinelle_input_guardrail(client)],
    output_guardrails=[zentinelle_output_guardrail(client)],
)

result = await Runner.run(agent, "...", hooks=ZentinelleRunHooks(client))
```

A denial surfaces as the SDK's own `InputGuardrailTripwireTriggered` /
`OutputGuardrailTripwireTriggered`, or as `PolicyViolationError` for a refused
tool call.

## Defaults worth knowing

**Traces stay inside your boundary.** `configure()` does not send traces to
OpenAI. The stock exporter uploads prompts, tool arguments and outputs to
OpenAI's trace store, which would undo the deployment for anyone running
Zentinelle to keep that content in their own systems. Pass
`send_traces_to_openai=True` to opt back in.

**Span contents are not recorded.** `ZentinelleTracingProcessor` records the
shape of a run — agents, tools, models, handoffs, errors, timings — and not the
text flowing through it. An audit trail holding a second copy of every prompt is
a second copy to secure. Pass `include_span_data=True` if you want it.

**Checks fail closed.** If the control plane cannot be reached, a request or
tool call is refused. Pass `fail_open=True` to prefer availability; the
resulting `EvaluateResult` is marked so the choice is visible in the audit
trail.

**The input guardrail runs before the agent, not alongside it.** The SDK's
default (`run_in_parallel=True`) is right for scoring and wrong for
enforcement: a parallel guardrail's denial arrives after the model call has
already been made.

## Provider credentials

`api_key` is what the gateway authenticates the *agent* with, not the provider
key. A deployment that holds provider credentials at the gateway never puts
them in the agent process, which is the point: a key that was never there
cannot leak from there. If the gateway is not holding the key, it forwards
whichever one it is given.

## Token accounting

The Agents SDK calls the OpenAI Responses API by default, which reports
`input_tokens` / `output_tokens` rather than the Chat Completions
`prompt_tokens` / `completion_tokens`. Gateway builds before that was handled
metered these runs as zero, so cost policies and usage limits saw nothing.
Recorded here because an old gateway paired with this plugin is silently
unmetered rather than visibly broken.
