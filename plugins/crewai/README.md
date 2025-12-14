# Zentinelle CrewAI Integration

[![PyPI](https://img.shields.io/pypi/v/zentinelle-crewai)](https://pypi.org/project/zentinelle-crewai)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Enterprise governance for CrewAI multi-agent systems. Add policy enforcement, cost controls, and comprehensive monitoring to your AI crews.

## Installation

```bash
pip install zentinelle-crewai
```

## Quick Start

```python
from crewai import Task
from zentinelle import ZentinelleClient
from zentinelle_crewai import GovernedCrew, GovernedAgent, GovernedTask

# Initialize Zentinelle
client = ZentinelleClient(
    api_key="your-api-key",
    agent_id="your-agent-id"
)

# Create governed agents
researcher = GovernedAgent(
    client=client,
    role="Senior Researcher",
    goal="Find accurate and comprehensive information",
    backstory="Expert researcher with years of experience",
    risk_level="medium",
    max_tokens_per_task=4000
)

writer = GovernedAgent(
    client=client,
    role="Content Writer",
    goal="Create engaging and accurate content",
    backstory="Skilled writer with attention to detail",
    risk_level="low"
)

# Create governed tasks
research_task = GovernedTask(
    client=client,
    description="Research the latest trends in AI governance",
    expected_output="Comprehensive research report",
    risk_level="medium",
    agent=researcher
)

writing_task = GovernedTask(
    client=client,
    description="Write an article based on the research",
    expected_output="Well-structured article",
    risk_level="low",
    agent=writer
)

# Create governed crew with cost limits
crew = GovernedCrew(
    client=client,
    agents=[researcher, writer],
    tasks=[research_task, writing_task],
    max_total_cost=1.00,  # $1 limit
    max_total_tokens=10000,
    verbose=True
)

# Execute with governance
result = crew.kickoff()
print(result)

# Check usage
print(crew.get_usage_summary())
```

## Features

### Governed Agents

Control what agents can do:

```python
from zentinelle_crewai import GovernedAgent

agent = GovernedAgent(
    client=client,
    role="Data Analyst",
    goal="Analyze data accurately",
    backstory="Expert data analyst",

    # Governance options
    allowed_tools=["calculator", "file_reader"],  # Restrict tools
    max_tokens_per_task=4000,                      # Token limits
    require_approval_for=["file_writer"],          # Human approval
    risk_level="medium"                            # Risk classification
)

# Check tool permissions
result = agent.can_use_tool("database_query")
if result.allowed:
    # Execute tool
    pass
else:
    print(f"Blocked: {result.reason}")

# Check model requests
result = agent.check_model_request("gpt-4", estimated_tokens=500)
```

### Governed Tasks

Add governance to individual tasks:

```python
from zentinelle_crewai import GovernedTask, TaskApprovalRequired

task = GovernedTask(
    client=client,
    description="Process customer financial data",
    expected_output="Analysis report",

    # Governance options
    risk_level="high",
    require_approval=True,
    sensitive_fields=["ssn", "credit_card"],
    max_output_length=10000,
    output_validators=[validate_no_pii]
)

try:
    result = task.check_execution_policy()
except TaskApprovalRequired as e:
    print(f"Approval needed: {e.workflow_id}")
    # Request approval via Zentinelle workflow
```

### Governed Tools

Wrap tools with policy enforcement:

```python
from zentinelle_crewai import GovernedTool, governed_tool

# Using class
search_tool = GovernedTool(
    client=client,
    name="web_search",
    description="Search the web",
    func=search_function,
    risk_level="medium",
    max_calls_per_session=10,
    cost_per_call=0.01
)

# Using decorator
@governed_tool(
    client=client,
    name="calculator",
    description="Perform calculations",
    risk_level="low"
)
def calculate(expression: str) -> float:
    """Calculate a mathematical expression."""
    # WARNING: Use a safe math parser in production, never eval()
    import ast
    return ast.literal_eval(expression)  # Only evaluates literals
```

### Governed Crews

Enterprise controls for multi-agent systems:

```python
from zentinelle_crewai import GovernedCrew

crew = GovernedCrew(
    client=client,
    agents=[researcher, writer, editor],
    tasks=[research_task, write_task, edit_task],

    # Cost controls
    max_total_cost=5.00,       # $5 limit for entire crew
    max_total_tokens=50000,    # Token limit

    # Approval workflow
    require_approval=True,

    # Session metadata
    session_metadata={
        "user_id": "user-123",
        "project": "blog-content"
    }
)

# Execute with automatic governance
result = crew.kickoff(inputs={"topic": "AI Safety"})

# Monitor usage
summary = crew.get_usage_summary()
print(f"Total cost: ${summary['total_cost']:.4f}")
print(f"Tokens used: {summary['total_tokens']}")
```

### Callback Handler

Track all crew activity:

```python
from zentinelle_crewai import ZentinelleCrewCallback

callback = ZentinelleCrewCallback(
    client=client,
    track_prompts=False,     # Don't log prompts (privacy)
    track_outputs=True,      # Log outputs
    max_output_length=500    # Truncate long outputs
)

# Add to crew
crew = Crew(
    agents=[...],
    tasks=[...],
    callbacks=[callback]
)
```

## Human-in-the-Loop

Handle approval workflows:

```python
from zentinelle_crewai import (
    GovernedTask,
    TaskApprovalRequired,
    ToolApprovalRequired
)

try:
    # Task that might need approval
    task = GovernedTask(
        client=client,
        description="Delete user data",
        risk_level="critical",
        require_approval=True
    )

    result = task.check_execution_policy()

except TaskApprovalRequired as e:
    # Send to approval workflow
    print(f"Task requires approval")
    print(f"Workflow ID: {e.workflow_id}")
    print(f"Reason: {e.reason}")

    # Wait for approval via Zentinelle dashboard
    # Or implement custom approval logic
```

## Cost Tracking

Monitor and control costs:

```python
# Set limits on crew
crew = GovernedCrew(
    client=client,
    agents=agents,
    tasks=tasks,
    max_total_cost=10.00,
    max_total_tokens=100000
)

# During execution, costs are tracked automatically
result = crew.kickoff()

# Get detailed usage
summary = crew.get_usage_summary()
print(f"Total cost: ${summary['total_cost']:.4f}")
print(f"Cost remaining: ${summary['cost_remaining']:.4f}")
print(f"Tokens used: {summary['total_tokens']}")
print(f"Tokens remaining: {summary['tokens_remaining']}")

# Manual cost recording
result = crew.record_cost(
    cost=0.05,
    tokens=1000,
    model="gpt-4"
)

if not result.allowed:
    print(f"Limit exceeded: {result.reason}")
```

## Risk Levels

Classify components by risk:

| Level | Use Case | Default Behavior |
|-------|----------|------------------|
| `low` | Read-only tools, simple calculations | Always allowed |
| `medium` | Web searches, file reading | Policy check |
| `high` | Data modification, API calls | Requires justification |
| `critical` | Deletions, financial actions | Human approval required |

```python
# Agent with risk level
agent = GovernedAgent(
    client=client,
    role="Admin",
    risk_level="high",  # All actions get extra scrutiny
    require_approval_for=["delete_user", "modify_permissions"]
)

# Task with risk level
task = GovernedTask(
    client=client,
    description="Delete inactive accounts",
    risk_level="critical",
    require_approval=True
)
```

## Best Practices

1. **Set appropriate risk levels**: Match risk to actual impact
2. **Use cost limits**: Prevent runaway spending
3. **Require approval for critical actions**: Human oversight for important decisions
4. **Track all activity**: Use callbacks for comprehensive monitoring
5. **Limit tool access**: Only give agents tools they need
6. **Validate outputs**: Check for sensitive data before returning

## Requirements

- Python 3.9+
- CrewAI 0.28.0+
- zentinelle 0.1.0+

## License

Apache 2.0

## Support

- Documentation: [https://docs.zentinelle.ai/integrations/crewai](https://docs.zentinelle.ai/integrations/crewai)
- Issues: [https://github.com/zentinelle/zentinelle-python/issues](https://github.com/zentinelle/zentinelle-python/issues)
- Email: support@zentinelle.ai
