"""The structure of a markdown document, as a pure function: ``outline(text)``.

No I/O, no limits: the tools that use it decide what to show. It knows three things:
the keys of the YAML front matter, the headings (``#`` to ``######``) and the
labelled lines (``**Label:** value``). Fenced code (``` or ~~~) holds none of them.
"""

import re
from dataclasses import dataclass, field

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_LABEL = re.compile(r"^\s*(?:[-*]\s+)?\*\*([^*\n:]{1,60}?):\*\*[ \t]*(.*?)\s*$")
_KEY = re.compile(r"^([A-Za-z0-9_][\w .-]*?):[ \t]*(.*?)\s*$")
_ITEM = re.compile(r"^\s*-\s")


@dataclass(frozen=True)
class FrontMatterKey:
    key: str
    value: str  # as written; "" when the value is a list or a block
    items: int = 0  # the entries of a list value


@dataclass(frozen=True)
class Heading:
    level: int
    title: str


@dataclass
class Label:
    label: str
    count: int = 0
    example: str = ""  # the first non-empty value


@dataclass
class Outline:
    length: int = 0
    front_matter: list[FrontMatterKey] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)  # in order of first occurrence


def _front_matter(lines: list[str]) -> tuple[list[FrontMatterKey], int]:
    """The keys of the front matter and the index of the first line after it."""
    if not lines or lines[0].strip() != "---":
        return [], 0
    end = next((i for i, ln in enumerate(lines[1:], 1) if ln.strip() == "---"), None)
    if end is None:
        return [], 0
    keys: list[FrontMatterKey] = []
    for line in lines[1:end]:
        if line[:1] in (" ", "\t", "#", "-") or not line.strip():
            if keys and _ITEM.match(line):
                last = keys[-1]
                keys[-1] = FrontMatterKey(last.key, last.value, last.items + 1)
            continue
        match = _KEY.match(line)
        if match:
            value = match.group(2).strip().strip("\"'")
            keys.append(FrontMatterKey(match.group(1), value))
    return keys, end + 1


def outline(text: str) -> Outline:
    result = Outline(length=len(text))
    lines = text.splitlines()
    result.front_matter, start = _front_matter(lines)
    labels: dict[str, Label] = {}
    fence = ""
    for line in lines[start:]:
        marker = _FENCE.match(line)
        if fence:
            if (
                marker
                and marker.group(1)[0] == fence[0]
                and len(marker.group(1)) >= len(fence)
            ):
                if not line.strip().lstrip(fence[0]):
                    fence = ""
            continue
        if marker:
            fence = marker.group(1)
            continue
        heading = _HEADING.match(line)
        if heading:
            result.headings.append(Heading(len(heading.group(1)), heading.group(2)))
            continue
        label = _LABEL.match(line)
        if label:
            entry = labels.setdefault(
                label.group(1).strip(), Label(label.group(1).strip())
            )
            entry.count += 1
            if not entry.example:
                entry.example = label.group(2)
    result.labels = list(labels.values())
    return result
