# zentinelle-langchain

Zentinelle governance for [LangChain](https://github.com/langchain-ai/langchain) and LangGraph.

`agent_type`: `langchain` (LangGraph runs on the same plugin; use `langgraph` if you want them told apart)

## What it provides

| Export | Role |
|---|---|
| `ZentinelleCallbackHandler` | records LLM calls, tool use and chain execution |
| `ZentinelleGuardrail` | a Runnable that enforces policy between chain steps |
| `ZentinelleToolWrapper` | wraps a tool so a denied call does not run |
| `ZentinelleRunnable` | governed Runnable wrapper |

## Install

```bash
pip install zentinelle-langchain
```

## Use

```python
from langchain_openai import ChatOpenAI
from zentinelle_langchain import ZentinelleCallbackHandler, ZentinelleGuardrail

handler = ZentinelleCallbackHandler(
    api_key="sk_agent_...",
    agent_type="langchain",
)

llm = ChatOpenAI(callbacks=[handler])

guardrail = ZentinelleGuardrail(handler.client)
chain = guardrail | prompt | llm | guardrail.output()
```

The callback handler is observability; the guardrail and the tool wrapper are
enforcement. A callback cannot stop anything, so a deployment that needs
policy applied rather than recorded wants at least one of the other two.
