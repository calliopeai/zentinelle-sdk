#!/usr/bin/env python3
"""
Tool-Using Agent Template - Zentinelle Integration

An agent with tool capabilities and governance:
- Tool call policy enforcement
- Dangerous tool blocking
- Tool usage tracking
- Human-in-the-loop for high-risk actions

Usage:
    pip install zentinelle openai
    export ZENTINELLE_API_KEY=sk_agent_...
    export OPENAI_API_KEY=sk-...
    python main.py
"""
import os
import json
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass

from openai import OpenAI
from zentinelle import ZentinelleClient, EvaluateResult


@dataclass
class Tool:
    """Tool definition."""
    name: str
    description: str
    parameters: Dict[str, Any]
    function: Callable
    risk_level: str = "low"  # low, medium, high


class GovernedToolAgent:
    """Agent with governed tool execution."""

    def __init__(
        self,
        zentinelle_api_key: str,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ):
        self.openai = OpenAI(api_key=openai_api_key)
        self.model = model

        self.zentinelle = ZentinelleClient(
            api_key=zentinelle_api_key,
            agent_type="tool-agent",
            fail_open=False,  # Strict mode for tools
        )

        self.zentinelle.register(
            capabilities=["chat", "tools"],
            metadata={
                "template": "tool-agent",
                "model": model,
            },
        )

        # Register tools
        self.tools: Dict[str, Tool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """Register default tools."""

        # Calculator - low risk
        self.register_tool(Tool(
            name="calculator",
            description="Perform mathematical calculations",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate",
                    },
                },
                "required": ["expression"],
            },
            function=self._calculator,
            risk_level="low",
        ))

        # Weather - low risk (mock)
        self.register_tool(Tool(
            name="get_weather",
            description="Get current weather for a location",
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name",
                    },
                },
                "required": ["location"],
            },
            function=self._get_weather,
            risk_level="low",
        ))

        # Web search - medium risk
        self.register_tool(Tool(
            name="web_search",
            description="Search the web for information",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                },
                "required": ["query"],
            },
            function=self._web_search,
            risk_level="medium",
        ))

        # File operations - high risk
        self.register_tool(Tool(
            name="write_file",
            description="Write content to a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write",
                    },
                },
                "required": ["path", "content"],
            },
            function=self._write_file,
            risk_level="high",
        ))

    def register_tool(self, tool: Tool):
        """Register a tool."""
        self.tools[tool.name] = tool

    def _calculator(self, expression: str) -> str:
        """Safe calculator implementation."""
        try:
            # Only allow safe math operations
            allowed = set('0123456789+-*/().^ ')
            if not all(c in allowed for c in expression):
                return "Invalid characters in expression"
            result = eval(expression, {"__builtins__": {}}, {})
            return str(result)
        except Exception as e:
            return f"Error: {e}"

    def _get_weather(self, location: str) -> str:
        """Mock weather function."""
        # In production, call a weather API
        return f"Weather in {location}: 72°F, Sunny"

    def _web_search(self, query: str) -> str:
        """Mock web search."""
        # In production, call a search API
        return f"Search results for '{query}': [Mock results - integrate real search API]"

    def _write_file(self, path: str, content: str) -> str:
        """File write with governance (blocked by default)."""
        # This would be blocked by policy in production
        return f"[BLOCKED] Would write to {path}"

    def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> str:
        """
        Execute a tool with governance checks.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            user_id: User identifier

        Returns:
            Tool execution result
        """
        tool = self.tools.get(tool_name)
        if not tool:
            return f"Unknown tool: {tool_name}"

        # Evaluate tool call policy
        result = self.zentinelle.evaluate(
            action="tool_call",
            user_id=user_id,
            context={
                "tool": tool_name,
                "risk_level": tool.risk_level,
                "arguments": {k: str(v)[:100] for k, v in arguments.items()},
            },
        )

        if not result.allowed:
            self.zentinelle.emit("tool_blocked", {
                "tool": tool_name,
                "reason": result.reason,
            }, category="audit", user_id=user_id)
            return f"[Tool blocked by policy: {result.reason}]"

        # Check for human approval on high-risk tools
        if tool.risk_level == "high":
            # In production, this would pause and wait for approval
            print(f"\n[Human approval required for {tool_name}]")
            approval = input("Approve? (yes/no): ").strip().lower()
            if approval != "yes":
                return "[Tool execution cancelled by user]"

        # Execute the tool
        try:
            output = tool.function(**arguments)

            self.zentinelle.emit_tool_call(
                tool_name=tool_name,
                user_id=user_id,
                inputs=arguments,
                outputs={"result": str(output)[:500]},
            )

            return output

        except Exception as e:
            self.zentinelle.emit("tool_error", {
                "tool": tool_name,
                "error": str(e),
            }, category="alert", user_id=user_id)
            return f"Tool error: {e}"

    def chat(
        self,
        message: str,
        user_id: Optional[str] = None,
        conversation: Optional[List[Dict]] = None,
    ) -> str:
        """
        Chat with tool-using capability.

        Args:
            message: User message
            user_id: User identifier
            conversation: Conversation history

        Returns:
            Assistant response
        """
        if conversation is None:
            conversation = []

        # Build OpenAI tools format
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self.tools.values()
        ]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant with access to tools. "
                    "Use tools when appropriate to help answer questions."
                ),
            },
            *conversation,
            {"role": "user", "content": message},
        ]

        # Get initial response
        response = self.openai.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
        )

        assistant_message = response.choices[0].message

        # Handle tool calls
        if assistant_message.tool_calls:
            tool_results = []

            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                print(f"[Calling tool: {tool_name}]")
                result = self.execute_tool(tool_name, arguments, user_id)

                tool_results.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "content": result,
                })

            # Get final response with tool results
            messages.append(assistant_message)
            messages.extend(tool_results)

            final_response = self.openai.chat.completions.create(
                model=self.model,
                messages=messages,
            )

            return final_response.choices[0].message.content

        return assistant_message.content

    def shutdown(self):
        """Clean shutdown."""
        self.zentinelle.shutdown()


def main():
    """Demo the tool agent."""
    agent = GovernedToolAgent(
        zentinelle_api_key=os.environ.get("ZENTINELLE_API_KEY", ""),
    )

    user_id = "demo-user"

    print("Tool Agent with Zentinelle Governance")
    print("=" * 40)
    print("Available tools:", ", ".join(agent.tools.keys()))
    print("Type 'quit' to exit\n")

    conversation = []

    try:
        while True:
            message = input("You: ").strip()
            if message.lower() in ['quit', 'exit', 'q']:
                break
            if not message:
                continue

            response = agent.chat(message, user_id=user_id, conversation=conversation)
            print(f"\nAssistant: {response}\n")

            # Update conversation history
            conversation.append({"role": "user", "content": message})
            conversation.append({"role": "assistant", "content": response})

    except KeyboardInterrupt:
        print("\nGoodbye!")
    finally:
        agent.shutdown()


if __name__ == "__main__":
    main()
