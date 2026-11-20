"""Every built-in template has a sample document the scripted extractor reads."""

from typing import Any

import pytest

from apps.documents import selectors as documents
from apps.extraction.extractors.base import Definition
from apps.extraction.extractors.scripted import ScriptedExtractor
from apps.extraction.template_registry import list_templates

SAMPLES = {
    "adr": "enriched/engineering/architecture/architecture-decisions-2026.md",
    "skill": "enriched/engineering/operations/operations-skills.md",
    "policy-rule": "enriched/hr/policies/leave-rules-2027.md",
}
TEMPLATES = [t for t in list_templates() if t.id != "blank"]


def test_every_template_but_blank_has_a_sample() -> None:
    assert {t.id for t in TEMPLATES} == set(SAMPLES)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.id)
def test_the_sample_gives_records_with_every_field_filled(
    template: Any, user: Any
) -> None:
    text = documents.read_document(user, SAMPLES[template.id]).text
    draft = template.definition
    definition = Definition(0, draft.prompt, draft.record_types)
    records = ScriptedExtractor().extract(text, definition)
    assert len(records) >= 2
    filled = {v.field_id for r in records for v in r.values if v.value is not None}
    every = {f.id for rt in draft.record_types for f in rt.fields}
    assert every - filled == set()
