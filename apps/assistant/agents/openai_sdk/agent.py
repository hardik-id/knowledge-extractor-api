"""Puts the agent together: the instructions, the tools and the model. Nothing else."""

from agents import Agent, Model, ModelSettings

from apps.assistant.agents.openai_sdk.context import ReplyContext
from apps.assistant.agents.openai_sdk.instructions import INSTRUCTIONS
from apps.assistant.agents.openai_sdk.tools import TOOLS


def build_agent(model: Model) -> Agent[ReplyContext]:
    return Agent[ReplyContext](
        name="Knowledge Extractor assistant",
        instructions=INSTRUCTIONS,
        tools=list(TOOLS),
        model=model,
        model_settings=ModelSettings(store=False),
    )
