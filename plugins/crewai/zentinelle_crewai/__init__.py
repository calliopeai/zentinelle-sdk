"""
Zentinelle integration for CrewAI multi-agent systems.

This package provides governance, monitoring, and policy enforcement
for CrewAI crews and agents.

Example:
    from crewai import Agent, Task, Crew
    from zentinelle import ZentinelleClient
    from zentinelle_crewai import GovernedCrew, GovernedAgent

    client = ZentinelleClient(api_key="...", agent_id="...")

    researcher = GovernedAgent(
        client=client,
        role="Researcher",
        goal="Find accurate information",
        backstory="Expert researcher with attention to detail"
    )

    crew = GovernedCrew(
        client=client,
        agents=[researcher],
        tasks=[...],
        verbose=True
    )

    result = crew.kickoff()
"""

from zentinelle_crewai.agent import GovernedAgent, GovernedAgentExecutor
from zentinelle_crewai.crew import GovernedCrew
from zentinelle_crewai.task import GovernedTask, TaskApprovalRequired
from zentinelle_crewai.tools import GovernedTool, governed_tool
from zentinelle_crewai.callbacks import ZentinelleCrewCallback

__all__ = [
    "GovernedAgent",
    "GovernedAgentExecutor",
    "GovernedCrew",
    "GovernedTask",
    "TaskApprovalRequired",
    "GovernedTool",
    "governed_tool",
    "ZentinelleCrewCallback",
]

__version__ = "0.1.0"
