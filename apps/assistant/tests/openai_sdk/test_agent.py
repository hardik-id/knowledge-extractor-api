"""build_agent: instructions, tools and model, and nothing that needs Django or a client."""

import ast
from pathlib import Path

from agents.testing import ScriptedModel

from apps.assistant.agents.openai_sdk import agent
from apps.assistant.agents.openai_sdk.agent import build_agent
from apps.assistant.agents.openai_sdk.instructions import INSTRUCTIONS


def test_the_agent_has_the_instructions_both_tools_and_the_model() -> None:
    model = ScriptedModel([])
    built = build_agent(model)
    assert built.model is model
    assert built.instructions == INSTRUCTIONS
    assert {t.name for t in built.tools} == {
        "propose_definition",
        "read_document",
        "find_in_documents",
        "preview_extraction",
        "outline_document",
        "summarize_records",
    }
    assert built.model_settings.store is False


def test_agent_py_imports_neither_django_nor_an_openai_client() -> None:
    tree = ast.parse(Path(agent.__file__).read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert not {m for m in modules if m.split(".")[0] in {"django", "openai"}}
