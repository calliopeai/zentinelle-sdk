# Zentinelle LlamaIndex Integration

[![PyPI](https://img.shields.io/pypi/v/zentinelle-llamaindex)](https://pypi.org/project/zentinelle-llamaindex)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Enterprise governance for LlamaIndex RAG applications. Add policy enforcement, PII detection, source validation, and comprehensive monitoring to your retrieval-augmented generation systems.

## Installation

```bash
pip install zentinelle-llamaindex
```

## Quick Start

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.llms.openai import OpenAI
from zentinelle import ZentinelleClient
from zentinelle_llamaindex import (
    GovernedQueryEngine,
    GovernedLLM,
    ZentinelleCallbackHandler,
    PIIGuardrail,
)

# Initialize Zentinelle
client = ZentinelleClient(
    api_key="your-api-key",
    agent_id="your-agent-id"
)

# Add callback handler for tracking
from llama_index.core import Settings
handler = ZentinelleCallbackHandler(client)
Settings.callback_manager.add_handler(handler)

# Create governed LLM
base_llm = OpenAI(model="gpt-4")
llm = GovernedLLM(
    client=client,
    llm=base_llm,
    max_tokens_per_request=4000
)

# Load documents and create index
documents = SimpleDirectoryReader("./data").load_data()
index = VectorStoreIndex.from_documents(documents)

# Create governed query engine
engine = GovernedQueryEngine(
    client=client,
    engine=index.as_query_engine(llm=llm),
    max_queries_per_session=100,
    require_source_attribution=True
)

# Add PII guardrail
pii_guard = PIIGuardrail(client, block_on_detection=True)

# Query with governance
query = "What is the company refund policy?"
response = engine.query(query)

# Validate response for PII
safe_response = pii_guard.validate(str(response))
print(safe_response)
```

## Features

### Governed Query Engine

Control RAG queries with policy enforcement:

```python
from zentinelle_llamaindex import GovernedQueryEngine

engine = GovernedQueryEngine(
    client=client,
    engine=base_query_engine,

    # Query limits
    max_tokens_per_query=4000,
    max_queries_per_session=100,

    # Source tracking
    require_source_attribution=True,

    # Topic filtering
    allowed_topics=["policy", "procedures", "faq"],
    blocked_topics=["salary", "personal"],

    # User tracking
    user_id="user-123"
)

# Query with governance
response = engine.query("What is the vacation policy?")

# Check usage
summary = engine.get_usage_summary()
print(f"Queries: {summary['query_count']}")
print(f"Remaining: {summary['queries_remaining']}")

# Reset for new session
engine.reset_session()
```

### Governed Retriever

Control document retrieval with access policies:

```python
from zentinelle_llamaindex import GovernedRetriever

retriever = GovernedRetriever(
    client=client,
    retriever=base_retriever,

    # Collection access control
    allowed_collections=["public", "internal"],
    blocked_collections=["confidential"],

    # Result filtering
    max_results=10,
    min_score_threshold=0.5,

    user_id="user-123"
)

# Retrieve with governance
nodes = retriever.retrieve("company benefits")
```

### Governed LLM

Wrap any LlamaIndex LLM with governance:

```python
from llama_index.llms.openai import OpenAI
from zentinelle_llamaindex import GovernedLLM

base_llm = OpenAI(model="gpt-4")

llm = GovernedLLM(
    client=client,
    llm=base_llm,

    # Token/cost limits
    max_tokens_per_request=4000,
    max_cost_per_request=0.50,

    # Model restrictions
    allowed_models=["gpt-4", "gpt-4-turbo"],

    user_id="user-123"
)

# All LLM operations are governed
response = llm.complete("Summarize this document")
chat_response = llm.chat(messages)

# Streaming is also governed
for chunk in llm.stream_complete("Write a report"):
    print(chunk.delta, end="")

# Check usage
summary = llm.get_usage_summary()
print(f"Total tokens: {summary['total_tokens']}")
print(f"Total cost: ${summary['total_cost']:.4f}")
```

### Governed ReAct Agent

Build governed agents with tool controls:

```python
from zentinelle_llamaindex import GovernedReActAgent

agent = GovernedReActAgent.from_governed(
    client=client,
    tools=[search_tool, calculator_tool, file_tool],
    llm=llm,

    # Iteration limits
    max_iterations=10,

    # Cost controls
    max_cost=1.00,

    # Human approval for dangerous tools
    require_approval_for=["file_write", "database_modify"],

    user_id="user-123"
)

# Execute with governance
response = agent.chat("Analyze the sales data and create a report")

# Check execution
summary = agent.get_execution_summary()
print(f"Iterations: {summary['iterations']}")
print(f"Tool calls: {len(summary['tool_calls'])}")
print(f"Cost: ${summary['total_cost']:.4f}")
```

### Callback Handler

Track all LlamaIndex operations:

```python
from llama_index.core import Settings
from zentinelle_llamaindex import ZentinelleCallbackHandler

handler = ZentinelleCallbackHandler(
    client=client,
    track_embeddings=True,    # Track embedding operations
    track_retrieval=True,     # Track retrieval operations
    track_llm_inputs=False,   # Don't log prompts (privacy)
    user_id="user-123"
)

# Register globally
Settings.callback_manager.add_handler(handler)

# All LlamaIndex operations are now tracked:
# - LLM calls with token usage
# - Embedding operations
# - Retrieval operations
# - Query operations
# - Agent steps
```

## Guardrails

### PII Detection

Detect and block personally identifiable information:

```python
from zentinelle_llamaindex import PIIGuardrail

guardrail = PIIGuardrail(
    client=client,
    block_on_detection=True,

    # Choose which patterns to check
    patterns_to_check=["email", "phone", "ssn", "credit_card"],

    # Add custom patterns
    custom_patterns={
        "employee_id": r"EMP-\d{6}",
        "internal_code": r"INT-[A-Z]{3}-\d{4}"
    },

    # Optionally redact instead of block
    redact_instead_of_block=False
)

# Check content
result = guardrail.check(response_text)
if not result.allowed:
    print(f"PII detected: {result.reason}")

# Or validate (raises on detection)
try:
    safe_content = guardrail.validate(response_text)
except GuardrailViolation as e:
    print(f"Blocked: {e.reason}")

# Redact PII
redacted = guardrail.redact("Contact john@example.com")
# "Contact [EMAIL_REDACTED]"
```

### Content Moderation

Block inappropriate or harmful content:

```python
from zentinelle_llamaindex import ContentGuardrail

guardrail = ContentGuardrail(
    client=client,

    # Topic blocking
    blocked_topics=["violence", "illegal_activities", "adult_content"],

    # Keyword blocking
    blocked_keywords=["hack", "exploit", "bypass"],

    # Length limits
    max_length=10000,

    # Use Zentinelle for advanced moderation
    require_zentinelle_approval=True
)

result = guardrail.check(generated_content)
```

### Source Attribution

Ensure responses are grounded in sources:

```python
from zentinelle_llamaindex import SourceGuardrail

guardrail = SourceGuardrail(
    client=client,
    require_sources=True,
    min_sources=2,
    min_relevance_score=0.7,

    # Source type filtering
    allowed_source_types=["documentation", "policy", "faq"],
    blocked_source_types=["user_generated", "external"]
)

# Check with source context
result = guardrail.check(
    response_text,
    context={"sources": response.source_nodes}
)

if not result.allowed:
    print(f"Source validation failed: {result.reason}")
```

## Complete Example

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.llms.openai import OpenAI
from zentinelle import ZentinelleClient
from zentinelle_llamaindex import (
    GovernedQueryEngine,
    GovernedLLM,
    ZentinelleCallbackHandler,
    PIIGuardrail,
    ContentGuardrail,
    SourceGuardrail,
)

# Initialize
client = ZentinelleClient(
    api_key="your-api-key",
    agent_id="your-agent-id"
)

# Setup callback handler
handler = ZentinelleCallbackHandler(client, user_id="user-123")
Settings.callback_manager.add_handler(handler)

# Setup governed LLM
llm = GovernedLLM(
    client=client,
    llm=OpenAI(model="gpt-4"),
    max_tokens_per_request=4000,
    max_cost_per_request=0.50
)

# Create index
documents = SimpleDirectoryReader("./docs").load_data()
index = VectorStoreIndex.from_documents(documents)

# Create governed query engine
engine = GovernedQueryEngine(
    client=client,
    engine=index.as_query_engine(llm=llm),
    max_queries_per_session=100,
    require_source_attribution=True,
    user_id="user-123"
)

# Setup guardrails
pii_guard = PIIGuardrail(client, block_on_detection=True)
content_guard = ContentGuardrail(
    client,
    blocked_topics=["competitor_info"],
    max_length=5000
)
source_guard = SourceGuardrail(
    client,
    require_sources=True,
    min_sources=1,
    min_relevance_score=0.6
)

def safe_query(query: str) -> str:
    """Execute query with full governance pipeline."""
    # Execute governed query
    response = engine.query(query)

    # Validate sources
    source_result = source_guard.check(
        str(response),
        context={"sources": response.source_nodes}
    )
    if not source_result.allowed:
        return f"Unable to answer: {source_result.reason}"

    # Check for PII
    safe_response = pii_guard.validate(str(response))

    # Check content
    content_result = content_guard.check(safe_response)
    if not content_result.allowed:
        return f"Response blocked: {content_result.reason}"

    return safe_response

# Use
answer = safe_query("What is our refund policy?")
print(answer)
```

## Best Practices

1. **Always use callbacks**: Track all operations for audit
2. **Layer guardrails**: Combine PII, content, and source guards
3. **Set cost limits**: Prevent runaway spending
4. **Use source validation**: Ensure grounded responses
5. **Handle errors gracefully**: Catch `GuardrailViolation` exceptions
6. **Track user context**: Pass `user_id` for proper attribution

## Requirements

- Python 3.9+
- LlamaIndex 0.10.0+
- zentinelle 0.1.0+

## License

Apache 2.0

## Support

- Documentation: [https://docs.zentinelle.ai/integrations/llamaindex](https://docs.zentinelle.ai/integrations/llamaindex)
- Issues: [https://github.com/zentinelle/zentinelle-python/issues](https://github.com/zentinelle/zentinelle-python/issues)
- Email: support@zentinelle.ai
