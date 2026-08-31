# zentinelle-ms-agent

Zentinelle governance for the [Microsoft Agent Framework](https://github.com/microsoft/agent-framework),
which unifies AutoGen and Semantic Kernel.

`agent_type`: `ms-agent-framework`

## What it provides

| Export | Role |
|---|---|
| `ZentinelleAgentExtension` | agent extension: policy evaluation, telemetry, token accounting |
| `ZentinelleOrchestrator` / `GovernedAgent` | governed multi-agent orchestration |
| `ZentinelleToolPlugin` / `governed_tool` | tool calls checked before they run |
| `ZentinelleMemoryPlugin` | memory with compliance controls |

## Install

```bash
pip install zentinelle-ms-agent

# Azure AI backends
pip install "zentinelle-ms-agent[azure]"
```

## Use

```python
from agent_framework import Agent, ChatCompletionClient
from zentinelle_ms_agent import ZentinelleAgentExtension

extension = ZentinelleAgentExtension(
    api_key="sk_agent_...",
    agent_type="ms-agent-framework",
)

agent = Agent(
    name="assistant",
    client=ChatCompletionClient(...),
    extensions=[extension],
)

await agent.run("Help me with this task")
```

A blocked action raises `PolicyViolationError`, carrying the `EvaluateResult`
that refused it. `GovernanceConfig` controls what is evaluated
(`evaluate_messages`, `evaluate_tool_calls`, `track_token_usage`) and whether a
failed check refuses or allows (`fail_open`, off by default).
