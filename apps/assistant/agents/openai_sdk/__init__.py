"""The assistant as an LLM agent, built with the OpenAI Agents SDK.

``ASSISTANT_AGENT=openai`` chooses it. One module, one job: see
docs/assistant.md for the map and for adding a tool.
"""

from apps.assistant.agents.openai_sdk.runner import OpenAIAgent

__all__ = ["OpenAIAgent"]
