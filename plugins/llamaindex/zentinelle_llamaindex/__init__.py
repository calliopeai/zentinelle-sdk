"""
Zentinelle integration for LlamaIndex RAG applications.

This package provides governance, monitoring, and policy enforcement
for LlamaIndex queries, retrievers, and agents.

Example:
    from llama_index.core import VectorStoreIndex
    from zentinelle import ZentinelleClient
    from zentinelle_llamaindex import GovernedQueryEngine, ZentinelleCallback

    client = ZentinelleClient(api_key="...", agent_id="...")

    # Create governed query engine
    index = VectorStoreIndex.from_documents(documents)
    query_engine = GovernedQueryEngine(
        client=client,
        engine=index.as_query_engine(),
        max_tokens_per_query=4000
    )

    response = query_engine.query("What is the company policy?")
"""

from zentinelle_llamaindex.query_engine import GovernedQueryEngine
from zentinelle_llamaindex.retriever import GovernedRetriever
from zentinelle_llamaindex.agent import GovernedReActAgent
from zentinelle_llamaindex.callback import ZentinelleCallbackHandler
from zentinelle_llamaindex.llm import GovernedLLM
from zentinelle_llamaindex.guardrails import (
    PIIGuardrail,
    ContentGuardrail,
    SourceGuardrail,
)

__all__ = [
    "GovernedQueryEngine",
    "GovernedRetriever",
    "GovernedReActAgent",
    "ZentinelleCallbackHandler",
    "GovernedLLM",
    "PIIGuardrail",
    "ContentGuardrail",
    "SourceGuardrail",
]

__version__ = "0.1.0"
