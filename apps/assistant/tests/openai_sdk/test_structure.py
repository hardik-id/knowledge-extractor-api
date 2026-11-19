"""outline(text): a pure function, no workspace."""

from apps.assistant.agents.openai_sdk.tools._structure import outline

DOC = """---
document_type: "reference"
summary: "A log."
keywords:
  - "a"
  - "b"
---

# Title

## ADR-1: One

**Status:** Accepted
**Date:** 3 November 2026

```md
# not a heading
**Status:** not a label
```

### Context

## ADR-2: Two

**Status:** Proposed
**Date:**
"""


def test_front_matter_keys_with_values_and_list_sizes() -> None:
    keys = {k.key: k for k in outline(DOC).front_matter}
    assert list(keys) == ["document_type", "summary", "keywords"]
    assert keys["document_type"].value == "reference"
    assert keys["keywords"].value == "" and keys["keywords"].items == 2


def test_headings_in_order_with_levels() -> None:
    found = outline(DOC).headings
    assert [(h.level, h.title) for h in found] == [
        (1, "Title"),
        (2, "ADR-1: One"),
        (3, "Context"),
        (2, "ADR-2: Two"),
    ]


def test_labels_are_grouped_with_count_and_first_example() -> None:
    labels = {x.label: x for x in outline(DOC).labels}
    assert list(labels) == ["Status", "Date"]
    assert labels["Status"].count == 2 and labels["Status"].example == "Accepted"
    assert labels["Date"].count == 2 and labels["Date"].example == "3 November 2026"


def test_fenced_code_holds_no_headings_or_labels() -> None:
    found = outline("```\n# no\n**A:** b\n```\n~~~\n# no\n~~~\n# yes\n")
    assert [h.title for h in found.headings] == ["yes"]
    assert found.labels == []


def test_a_longer_fence_is_not_closed_by_a_shorter_one() -> None:
    found = outline("````\n```\n# no\n````\n# yes\n")
    assert [h.title for h in found.headings] == ["yes"]


def test_an_unclosed_front_matter_is_text() -> None:
    found = outline("---\n# Heading\n")
    assert found.front_matter == []
    assert [h.title for h in found.headings] == ["Heading"]


def test_an_empty_text() -> None:
    found = outline("")
    assert found.length == 0
    assert (found.front_matter, found.headings, found.labels) == ([], [], [])
