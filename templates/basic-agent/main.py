#!/usr/bin/env python3
"""
Basic Agent Template - Zentinelle Integration

A simple conversational agent with Zentinelle governance:
- Policy evaluation before AI requests
- Token usage tracking for cost control
- Event telemetry for observability

Usage:
    pip install zentinelle openai
    export ZENTINELLE_API_KEY=sk_agent_...
    export OPENAI_API_KEY=sk-...
    python main.py
"""
import os
import sys
from typing import Optional

from openai import OpenAI
from zentinelle import (
    ZentinelleClient,
    ZentinelleError,
    ZentinelleRateLimitError,
    ModelUsage,
)


def create_zentinelle_client() -> ZentinelleClient:
    """Create and register Zentinelle client."""
    api_key = os.environ.get('ZENTINELLE_API_KEY')
    if not api_key:
        print("Warning: ZENTINELLE_API_KEY not set, governance disabled")
        return None

    client = ZentinelleClient(
        api_key=api_key,
        agent_type="basic-chatbot",
        fail_open=True,  # Continue if Zentinelle unreachable
    )

    # Register agent on startup
    try:
        result = client.register(
            capabilities=["chat"],
            metadata={
                "template": "basic-agent",
                "version": "1.0.0",
            },
        )
        print(f"Agent registered: {result.agent_id}")
    except ZentinelleError as e:
        print(f"Warning: Registration failed: {e}")

    return client


def chat_completion(
    openai_client: OpenAI,
    zentinelle_client: Optional[ZentinelleClient],
    messages: list,
    user_id: str,
    model: str = "gpt-4o-mini",
) -> str:
    """
    Make a chat completion with Zentinelle governance.

    Args:
        openai_client: OpenAI client
        zentinelle_client: Zentinelle client (or None)
        messages: Conversation messages
        user_id: User identifier
        model: Model to use

    Returns:
        Assistant response text
    """
    # Evaluate policy before making AI request
    if zentinelle_client:
        try:
            result = zentinelle_client.evaluate(
                action="model_request",
                user_id=user_id,
                context={
                    "model": model,
                    "provider": "openai",
                    "message_count": len(messages),
                },
            )

            if not result.allowed:
                return f"[Blocked by policy: {result.reason}]"

            # Check warnings
            for warning in result.warnings:
                print(f"Policy warning: {warning}")

        except ZentinelleRateLimitError as e:
            return f"[Rate limited, retry after {e.retry_after}s]"
        except ZentinelleError as e:
            print(f"Governance check failed: {e}")
            # Continue anyway (fail_open)

    # Make the OpenAI request
    response = openai_client.chat.completions.create(
        model=model,
        messages=messages,
    )

    # Track token usage
    if zentinelle_client and response.usage:
        zentinelle_client.track_usage(ModelUsage(
            provider="openai",
            model=model,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
        ))

        # Emit completion event
        zentinelle_client.emit("chat_completion", {
            "model": model,
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
        }, category="telemetry", user_id=user_id)

    return response.choices[0].message.content


def main():
    """Run the basic agent."""
    # Initialize clients
    openai_client = OpenAI()
    zentinelle_client = create_zentinelle_client()

    # Example user
    user_id = "demo-user"

    print("Basic Agent with Zentinelle Governance")
    print("=" * 40)
    print("Type 'quit' to exit\n")

    messages = [
        {"role": "system", "content": "You are a helpful assistant."}
    ]

    try:
        while True:
            # Get user input
            user_input = input("You: ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                break
            if not user_input:
                continue

            # Add user message
            messages.append({"role": "user", "content": user_input})

            # Get response with governance
            response = chat_completion(
                openai_client,
                zentinelle_client,
                messages,
                user_id=user_id,
            )

            print(f"Assistant: {response}\n")

            # Add assistant response to history
            messages.append({"role": "assistant", "content": response})

    except KeyboardInterrupt:
        print("\nGoodbye!")
    finally:
        # Clean shutdown
        if zentinelle_client:
            zentinelle_client.shutdown()


if __name__ == "__main__":
    main()
