# Zentinelle SDKs & Integrations

AI Agent Governance SDKs, framework plugins, and templates.

## Overview

```
sdks/
├── python/              # Core Python SDK (zentinelle)
├── typescript/          # Core TypeScript SDK (zentinelle)
├── go/                  # Core Go SDK
├── java/                # Core Java SDK
├── csharp/              # Core C#/.NET SDK
├── plugins/
│   ├── langchain/       # LangChain integration
│   ├── llamaindex/      # LlamaIndex RAG integration
│   ├── crewai/          # CrewAI multi-agent integration
│   ├── ms-agent-framework/  # Microsoft Agent Framework integration
│   ├── vercel-ai/       # Vercel AI SDK integration
│   ├── n8n/             # n8n workflow automation nodes
│   └── langflow/        # LangFlow integration (coming soon)
└── templates/
    ├── basic-agent/     # Simple chat agent template
    ├── rag-agent/       # Retrieval-Augmented Generation template
    └── tool-agent/      # Tool-using agent template
```

## Quick Start

### TypeScript SDK

```bash
npm install zentinelle
```

```typescript
import { ZentinelleClient } from 'zentinelle';

const client = new ZentinelleClient({
  apiKey: 'sk_agent_...',
  agentId: 'my-agent',
});

// Register on startup
await client.register({ capabilities: ['chat', 'tools'] });

// Evaluate policies before actions
const result = await client.evaluate('tool_call', {
  userId: 'user123',
  context: { tool: 'web_search' },
});

if (!result.allowed) {
  throw new Error(result.reason);
}

// Track model usage
client.emit({
  category: 'model_request',
  action: 'gpt-4',
  modelUsage: { model: 'gpt-4', inputTokens: 100, outputTokens: 50 },
});
```

### Python SDK

```bash
pip install zentinelle
```

```python
from zentinelle import ZentinelleClient

client = ZentinelleClient(
    api_key="sk_agent_...",
    agent_id="my-agent",
)

# Register on startup
client.register(capabilities=["chat", "tools"])

# Evaluate policies before actions
result = client.evaluate("tool_call", user_id="user123", context={"tool": "web_search"})
if not result.allowed:
    raise PermissionError(result.reason)

# Track model usage
client.emit(
    category="model_request",
    action="gpt-4",
    model_usage=ModelUsage(model="gpt-4", input_tokens=100, output_tokens=50)
)
```

### Go SDK

```bash
go get github.com/zentinelle/zentinelle-go
```

```go
package main

import (
    "github.com/zentinelle/zentinelle-go/zentinelle"
)

func main() {
    client, _ := zentinelle.NewClient(
        zentinelle.WithAPIKey("sk_agent_..."),
        zentinelle.WithAgentID("my-agent"),
    )
    defer client.Close()

    // Evaluate policies
    result, _ := client.Evaluate("tool_call", &zentinelle.EvaluateOptions{
        UserID: "user123",
        Context: map[string]interface{}{"tool": "web_search"},
    })

    if !result.Allowed {
        log.Fatalf("Blocked: %s", result.Reason)
    }
}
```

### Java SDK

```xml
<dependency>
    <groupId>ai.zentinelle</groupId>
    <artifactId>zentinelle-sdk</artifactId>
    <version>0.1.0</version>
</dependency>
```

```java
import ai.zentinelle.ZentinelleClient;
import ai.zentinelle.model.*;

ZentinelleClient client = ZentinelleClient.builder()
    .apiKey("sk_agent_...")
    .agentId("my-agent")
    .build();

// Evaluate policies
EvaluateResult result = client.evaluate("tool_call",
    EvaluateOptions.builder()
        .context(Map.of("tool", "web_search"))
        .build());

if (!result.isAllowed()) {
    throw new RuntimeException("Blocked: " + result.getReason());
}

client.close();
```

### C#/.NET SDK

```bash
dotnet add package Zentinelle
```

```csharp
using Zentinelle;
using Zentinelle.Models;

var client = new ZentinelleClient(new ZentinelleOptions
{
    ApiKey = "sk_agent_...",
    AgentId = "my-agent"
});

// Evaluate policies
var result = await client.EvaluateAsync("tool_call", new EvaluateOptions
{
    Context = new Dictionary<string, object> { ["tool"] = "web_search" }
});

if (!result.Allowed)
{
    throw new Exception($"Blocked: {result.Reason}");
}

await client.DisposeAsync();
```

## Framework Integrations

### LangChain

```bash
pip install zentinelle-langchain
```

```python
from langchain_openai import ChatOpenAI
from zentinelle_langchain import ZentinelleCallbackHandler, ZentinelleGuardrail

# Add callback handler for observability
handler = ZentinelleCallbackHandler(api_key="sk_agent_...")
llm = ChatOpenAI(callbacks=[handler])

# Add guardrails to chains
guardrail = ZentinelleGuardrail(handler.client)
chain = guardrail | prompt | llm | guardrail.output()
```

### LlamaIndex

```bash
pip install zentinelle-llamaindex
```

```python
from llama_index.core import VectorStoreIndex
from zentinelle import ZentinelleClient
from zentinelle_llamaindex import GovernedQueryEngine, PIIGuardrail

client = ZentinelleClient(api_key="sk_agent_...", agent_id="my-agent")

# Governed RAG query engine
index = VectorStoreIndex.from_documents(documents)
engine = GovernedQueryEngine(
    client=client,
    engine=index.as_query_engine(),
    max_queries_per_session=100,
    require_source_attribution=True
)

# Add PII guardrail
pii_guard = PIIGuardrail(client, block_on_detection=True)
response = engine.query("What is the refund policy?")
safe_response = pii_guard.validate(str(response))
```

### CrewAI

```bash
pip install zentinelle-crewai
```

```python
from crewai import Task
from zentinelle import ZentinelleClient
from zentinelle_crewai import GovernedCrew, GovernedAgent

client = ZentinelleClient(api_key="sk_agent_...", agent_id="my-agent")

# Governed multi-agent crew
researcher = GovernedAgent(
    client=client,
    role="Researcher",
    goal="Find accurate information",
    risk_level="medium",
    max_tokens_per_task=4000
)

crew = GovernedCrew(
    client=client,
    agents=[researcher],
    tasks=[research_task],
    max_total_cost=1.00  # $1 budget
)

result = crew.kickoff()
print(crew.get_usage_summary())
```

### Vercel AI SDK

```bash
npm install zentinelle-ai zentinelle
```

```typescript
import { openai } from '@ai-sdk/openai';
import { createGovernedAI } from 'zentinelle-ai';
import { z } from 'zod';

const governed = createGovernedAI({
  apiKey: 'sk_agent_...',
  agentId: 'vercel-ai',
});

// Governed text generation
const { text } = await governed.generateText({
  model: openai('gpt-4o'),
  prompt: 'Hello!',
  userId: 'user123',
});

// Governed tools
const calculator = governed.tool({
  name: 'calculator',
  description: 'Perform calculations',
  parameters: z.object({ expression: z.string() }),
  execute: async ({ expression }) => eval(expression),
  riskLevel: 'low',
});
```

### Microsoft Agent Framework

```bash
pip install zentinelle-ms-agent
```

```python
from zentinelle_ms_agent import ZentinelleAgentExtension, ZentinelleOrchestrator

# Add extension to agents
extension = ZentinelleAgentExtension(api_key="sk_agent_...")
agent = Agent(name="assistant", extensions=[extension])

# Governed multi-agent orchestration
orchestrator = ZentinelleOrchestrator(
    api_key="sk_agent_...",
    agents=[
        GovernedAgent(name="planner", allowed_tools=["search"]),
        GovernedAgent(name="executor", allowed_tools=["code"]),
    ],
)
```

### n8n

Install the `n8n-nodes-zentinelle` package in your n8n instance.

Nodes available:
- **Zentinelle** - Policy evaluation, events, config, secrets
- **Zentinelle Guardrail** - Policy enforcement gate with routing
- **Zentinelle Trigger** - Webhook triggers for Zentinelle events

## Agent Templates

Ready-to-use templates demonstrating Zentinelle integration:

### Basic Agent
Simple conversational agent with governance.

```bash
cd templates/basic-agent
pip install -r requirements.txt
python main.py
```

### RAG Agent
Retrieval-Augmented Generation with PII detection and source tracking.

```bash
cd templates/rag-agent
pip install -r requirements.txt
python main.py
```

### Tool Agent
Tool-using agent with policy enforcement and human-in-the-loop.

```bash
cd templates/tool-agent
pip install -r requirements.txt
python main.py
```

## Features

### Policy Enforcement
- Rate limiting
- Cost controls
- PII detection
- Model restrictions
- Tool allowlists/blocklists
- Human-in-the-loop approval

### Observability
- Token usage tracking
- Event telemetry
- Audit logging
- Error tracking
- Distributed tracing

### Compliance
- GDPR data retention
- HIPAA PII handling
- SOC2 audit trails
- EU AI Act risk classification

### Enterprise Resilience
- Circuit breaker pattern
- Retry with exponential backoff
- Fail-open mode for non-critical paths
- Event buffering and batching

## SDK Comparison

| Feature | Python | TypeScript | Go | Java | C# |
|---------|--------|------------|----|----|-----|
| Async Support | ✅ | ✅ | ✅ (goroutines) | ✅ (CompletableFuture) | ✅ |
| Circuit Breaker | ✅ | ✅ | ✅ | ✅ | ✅ |
| Event Buffering | ✅ | ✅ | ✅ | ✅ | ✅ |
| Config Caching | ✅ | ✅ | ✅ | ✅ | ✅ |
| Fail-Open Mode | ✅ | ✅ | ✅ | ✅ | ✅ |
| Heartbeats | ✅ | ✅ | ✅ | ✅ | ✅ |

## Documentation

- [Zentinelle Docs](https://docs.zentinelle.ai)
- [API Reference](https://docs.zentinelle.ai/api)
- [Integration Guides](https://docs.zentinelle.ai/integrations)

## License

Apache-2.0
