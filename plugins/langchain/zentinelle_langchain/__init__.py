"""
Zentinelle LangChain Integration - AI Agent Governance for LangChain.

This package provides:
- ZentinelleCallbackHandler: Track LLM calls, tool usage, and chain execution
- ZentinelleGuardrail: Runnable that enforces policies before/after chain steps
- ZentinelleToolWrapper: Wrap tools with policy enforcement

Usage:
    from langchain_openai import ChatOpenAI
    from zentinelle_langchain import ZentinelleCallbackHandler, ZentinelleGuardrail

    # Add callback handler for observability
    handler = ZentinelleCallbackHandler(
        api_key="sk_agent_...",
        agent_type="langchain",
    )

    llm = ChatOpenAI(callbacks=[handler])

    # Add guardrails to chain
    guardrail = ZentinelleGuardrail(handler.client)
    chain = guardrail | prompt | llm | guardrail.output()
"""
from .callback import ZentinelleCallbackHandler
from .guardrail import ZentinelleGuardrail, ZentinelleToolWrapper
from .runnable import ZentinelleRunnable

__all__ = [
    'ZentinelleCallbackHandler',
    'ZentinelleGuardrail',
    'ZentinelleToolWrapper',
    'ZentinelleRunnable',
]

__version__ = '0.1.0'
