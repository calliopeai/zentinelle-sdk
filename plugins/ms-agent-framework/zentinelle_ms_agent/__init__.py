"""
Zentinelle Microsoft Agent Framework Integration - AI Agent Governance.

This package provides governance capabilities for Microsoft Agent Framework agents:
- ZentinelleAgentExtension: Extension for agents with policy enforcement
- ZentinelleOrchestrator: Governed multi-agent orchestration
- ZentinelleMemoryPlugin: Pluggable memory with compliance controls

Microsoft Agent Framework unifies AutoGen and Semantic Kernel into a commercial-grade
framework for building, orchestrating, and deploying AI agents.

Usage:
    from agent_framework import Agent, ChatCompletionClient
    from zentinelle_ms_agent import ZentinelleAgentExtension

    # Create governed agent
    extension = ZentinelleAgentExtension(
        api_key="sk_agent_...",
        agent_type="ms-agent-framework",
    )

    agent = Agent(
        name="assistant",
        client=ChatCompletionClient(...),
        extensions=[extension],
    )

    # Extension handles policy evaluation, telemetry, and compliance
    await agent.run("Help me with this task")
"""
from .extension import ZentinelleAgentExtension
from .orchestrator import ZentinelleOrchestrator, GovernedAgent
from .memory import ZentinelleMemoryPlugin
from .tools import ZentinelleToolPlugin, governed_tool

__all__ = [
    'ZentinelleAgentExtension',
    'ZentinelleOrchestrator',
    'GovernedAgent',
    'ZentinelleMemoryPlugin',
    'ZentinelleToolPlugin',
    'governed_tool',
]

__version__ = '0.1.0'
