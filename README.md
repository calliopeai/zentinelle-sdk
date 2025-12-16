# Zentinelle SDK

AI Agent Governance SDK for Python and TypeScript.

## Overview

```
python/                  # Core Python SDK (zentinelle)
typescript/              # Core TypeScript SDK (zentinelle)
plugins/
├── langchain/           # LangChain integration (coming soon)
├── llamaindex/          # LlamaIndex RAG integration (coming soon)
├── crewai/              # CrewAI multi-agent integration (coming soon)
├── ms-agent-framework/  # Microsoft Agent Framework integration (coming soon)
├── vercel-ai/           # Vercel AI SDK integration (coming soon)
└── n8n/                 # n8n workflow automation nodes (coming soon)
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

## Framework Integrations

Framework-specific integrations are coming soon:

- **LangChain** - Callback handlers and guardrails for LangChain
- **LlamaIndex** - Governed query engines and PII guardrails for RAG
- **CrewAI** - Multi-agent governance for CrewAI crews
- **Vercel AI SDK** - Governed text generation and tool use
- **Microsoft Agent Framework** - Extensions and orchestrators
- **n8n** - Workflow automation nodes

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

## SDK Features

| Feature | Python | TypeScript |
|---------|--------|------------|
| Async Support | ✅ | ✅ |
| Circuit Breaker | ✅ | ✅ |
| Event Buffering | ✅ | ✅ |
| Config Caching | ✅ | ✅ |
| Fail-Open Mode | ✅ | ✅ |
| Heartbeats | ✅ | ✅ |

## Documentation

- [Zentinelle Docs](https://docs.zentinelle.ai)
- [API Reference](https://docs.zentinelle.ai/api)
- [Integration Guides](https://docs.zentinelle.ai/integrations)

## License

MIT License

Copyright (c) 2025 Calliope Labs Inc. All Rights Reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
