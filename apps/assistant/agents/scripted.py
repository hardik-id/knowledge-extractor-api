"""The scripted assistant: keyword rules, no model, no key.

A port of the UI's ``src/services/mock/mock-assistant.ts``, so the chat can be
built and tried end to end. It is deterministic. It does not use the workspace.

Phrases it understands (case does not matter):

  bare prompt (a definition with no record types): "ADR" / "architecture
    decision", "policy" / "requirement" / "regulation" / "must", otherwise
    "extract <things> from ..."
  "add (a field for) X", "add X as inferred" (or derive / normalise / summarise)
  "remove X" / "drop X"
  "make X exact" / "quote" / "verbatim" / "inferred"
  "rename X to Y"
  "split A and B" (e.g. "split approver and approval date")
  "X can have several values"
  "output as json" / "csv" / "markdown"
  "use X in the template" / "add X to the template"

Anything else is answered with help and no proposal.
"""

import re
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass

from apps.assistant.agents.base import AgentEvent, Message, TextDelta, Workspace
from apps.assistant.proposal import Proposal, Reason
from apps.extraction.defaults import (
    DEFAULT_OUTPUT,
    DEFAULT_PROMPT,
    DEFAULT_RECORD_TYPES,
)
from apps.extraction.definition import Draft, Field, Output, RecordType

NewId = Callable[[], str]

EXAMPLES = (
    'Try "add a field for approval date" or "make approved by exact". '
    "I can also remove or rename a field, split one in two, allow several values, "
    "change the output to json, csv or markdown, or use a field in the template."
)


@dataclass(frozen=True)
class Reply:
    text: str
    proposal: Proposal | None


def _nothing(what: str) -> Reply:
    return Reply(f"{what} {EXAMPLES}", None)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def key_from_name(name: str) -> str:
    """Same rule as the field editor in the UI: lower case, other characters to ``_``."""
    return re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]+", "_", name.lower()))


def _unique_key(name: str, taken: Iterable[str]) -> str:
    used = set(taken)
    base = key_from_name(name) or "field"
    key = base
    n = 2
    while key in used:
        key = f"{base}_{n}"
        n += 1
    return key


def _words(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    text = re.sub(r"^(the|a|an)\s+", "", text)
    return re.sub(r"\s+field$", "", text)


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:]


def _clean_name(raw: str) -> str:
    name = re.sub(r"[\"'`]", "", raw)
    name = re.sub(r"^(?:a|an|the)\s+", "", name, flags=re.I)
    name = re.sub(r"\s+field$", "", name, flags=re.I).strip()
    return _capitalise(name)


def _make_field(
    name: str,
    ids: NewId,
    taken: Iterable[str],
    *,
    mode: str = "quote",
    value_type: str | None = None,
    multiple: bool = False,
    choices: list[str] | None = None,
) -> Field:
    if value_type is None:
        value_type = "date" if re.search(r"\bdate\b", name, re.I) else "text"
    return Field(
        id=ids(),
        key=_unique_key(name, taken),
        name=name,
        description=f"The {name.lower()}.",
        mode=mode,  # type: ignore[arg-type]
        value_type=value_type,  # type: ignore[arg-type]
        choices=choices or [],
        multiple=multiple,
    )


# Templates


def _template_line(field: Field) -> str:
    if field.multiple:
        key = field.key
        return f"**{field.name}:**\n{{{{#{key}}}}}- {{{{.}}}}\n{{{{/{key}}}}}"
    return f"**{field.name}:** {{{{{field.key}}}}}"


def _append_to_template(template: str, field: Field) -> str:
    key = field.key
    if f"{{{{{key}}}}}" in template or f"{{{{#{key}}}}}" in template:
        return template
    base = template if template.endswith("\n") or template == "" else f"{template}\n"
    return f"{base}\n{_template_line(field)}\n"


def _remove_from_template(template: str, field: Field) -> str:
    key = re.escape(field.key)
    name = re.escape(field.name)
    template = re.sub(rf"^\*\*{name}:\*\*[^\n]*\n?", "", template, flags=re.M)
    template = re.sub(rf"\{{\{{#{key}\}}\}}[\s\S]*?\{{\{{/{key}\}}\}}\n?", "", template)
    return re.sub(rf"^[^\n]*\{{\{{{key}\}}\}}[^\n]*\n?", "", template, flags=re.M)


def _template_for(record_type: RecordType) -> str:
    fields = record_type.fields
    if not fields:
        return ""
    first, rest = fields[0], fields[1:]
    lines = "\n".join(_template_line(field) for field in rest)
    return f"## {{{{{first.key}}}}}\n\n{lines}\n"


# Starting from a bare prompt


def _fresh_ids(record_types: list[RecordType], ids: NewId) -> list[RecordType]:
    copied = [record_type.model_copy(deep=True) for record_type in record_types]
    for record_type in copied:
        record_type.id = ids()
        for field in record_type.fields:
            field.id = ids()
    return copied


def _field_reasons(record_type: RecordType) -> list[Reason]:
    reasons = [
        Reason(
            path=record_type.name,
            reason=f"Looks for {record_type.description.lower()}",
        )
    ]
    for field in record_type.fields:
        if field.mode == "quote":
            reason = f"Copied exactly from the text. {field.description}"
        else:
            reason = (
                "Worked out from the text, with the passages it is based on. "
                f"{field.description}"
            )
        reasons.append(Reason(path=f"{record_type.name} / {field.name}", reason=reason))
    return reasons


def _main_noun(text: str) -> str | None:
    match = re.search(
        r"\b(?:extract|find|pull out|list|get|collect)\s+"
        r"(?:all\s+|every\s+|each\s+|the\s+|any\s+)*"
        r"([a-z][a-z -]*?)(?:\s+(?:from|in|of|out of|with)\b|[.,;:!?]|$)",
        text,
        re.I,
    )
    parts = match.group(1).strip().split() if match else []
    if not parts:
        return None
    last = parts[-1]
    singular = (
        last[:-1]
        if len(last) > 3
        and last.lower().endswith("s")
        and not last.lower().endswith("ss")
        else last
    )
    return _capitalise(singular.lower())


def _propose(definition: Draft, text: str, ids: NewId) -> Reply:
    haystack = f"{text} {definition.prompt}".lower()
    own_prompt = definition.prompt.strip()

    if re.search(r"\badrs?\b|architecture decision", haystack):
        next_definition = Draft(
            prompt=own_prompt or DEFAULT_PROMPT,
            record_types=_fresh_ids(
                [RecordType.model_validate(rt) for rt in DEFAULT_RECORD_TYPES], ids
            ),
            output=Output.model_validate(DEFAULT_OUTPUT),
        )
        reply = (
            "I set this up for architecture decision records: the title, the context and "
            "the decision are copied exactly, and the status and date are worked out from "
            "the text. The template shows each record as a short page."
        )
    elif re.search(r"\bpolic(?:y|ies)\b|requirement|regulation|\bmust\b", haystack):
        record_type_id = ids()
        requirement = _make_field("Requirement", ids, [], mode="quote")
        applies_to = _make_field("Applies to", ids, ["requirement"], mode="quote")
        category = _make_field(
            "Category",
            ids,
            ["requirement", "applies_to"],
            mode="inferred",
            value_type="choice",
            choices=["security", "privacy", "operational", "legal", "other"],
        )
        requirement.description = (
            "The requirement, in the exact wording of the document."
        )
        applies_to.description = "Who or what the requirement applies to."
        category.description = "The kind of requirement."
        record_type = RecordType(
            id=record_type_id,
            name="Requirement",
            description="One requirement a policy or regulation places on someone.",
            fields=[requirement, applies_to, category],
        )
        next_definition = Draft(
            prompt=own_prompt or "Extract every requirement in the document.",
            record_types=[record_type],
            output=Output(format="markdown", template=_template_for(record_type)),
        )
        reply = (
            "I chose exact quotes for the requirement and who it applies to, because "
            "requirements must not be reworded. The category is worked out from the text."
        )
    else:
        name = _main_noun(text) or _main_noun(definition.prompt) or "Item"
        lower = name.lower()
        record_type_id = ids()
        title = _make_field("Title", ids, [], mode="quote")
        summary = _make_field("Summary", ids, ["title"], mode="inferred")
        title.description = f"The title of the {lower}."
        summary.description = f"A short summary of the {lower}."
        record_type = RecordType(
            id=record_type_id,
            name=name,
            description=f"One {lower} found in the document.",
            fields=[title, summary],
        )
        next_definition = Draft(
            prompt=own_prompt or f"Extract every {lower} in the document.",
            record_types=[record_type],
            output=Output(format="markdown", template=_template_for(record_type)),
        )
        reply = (
            f"I started with one record type, {name}, with a title copied exactly and a "
            "summary worked out from the text. Ask me to add or change fields from here."
        )

    reasons: list[Reason] = [
        reason
        for record_type in next_definition.record_types
        for reason in _field_reasons(record_type)
    ]
    reasons.append(
        Reason(path="Template", reason="Shows each record using the field keys.")
    )
    return Reply(reply, Proposal(definition=next_definition, reasons=reasons))


# Changing an existing definition

Found = tuple[RecordType, int]


def _find_field(definition: Draft, phrase: str, message: str) -> Found | None:
    wanted = _words(phrase)
    if not wanted:
        return None
    lower = message.lower()
    types = sorted(
        definition.record_types,
        key=lambda record_type: 0 if record_type.name.lower() in lower else 1,
    )
    tests: list[Callable[[Field], bool]] = [
        lambda f: _words(f.name) == wanted or _words(f.key) == wanted,
        lambda f: f" {wanted} " in f" {_words(f.name)} ",
    ]
    for test in tests:
        for record_type in types:
            for index, field in enumerate(record_type.fields):
                if test(field):
                    return record_type, index
    return None


def _shares_stem(field: Field, phrase: str) -> bool:
    """ "approver" and "approved by" share a stem: used to find what "split approver and date" means."""
    a = _words(phrase).split(" ")[0]
    for w in _words(field.name).split(" "):
        n = 0
        while n < len(w) and n < len(a) and w[n] == a[n]:
            n += 1
        if n >= 5:
            return True
    return False


def _target_type(definition: Draft, message: str) -> RecordType:
    lower = message.lower()
    for record_type in definition.record_types:
        if record_type.name.lower() in lower:
            return record_type
    return definition.record_types[0]


def _not_found(phrase: str, definition: Draft) -> Reply:
    names = ", ".join(
        field.name
        for record_type in definition.record_types
        for field in record_type.fields
    )
    return _nothing(f'I can\'t find a field called "{phrase}". The fields are {names}.')


def _done(text: str, definition: Draft, reasons: list[Reason]) -> Reply:
    return Reply(text, Proposal(definition=definition, reasons=reasons))


def _mode_of(message: str) -> str:
    return (
        "inferred"
        if re.search(r"inferred|derive|normali[sz]|summar", message, re.I)
        else "quote"
    )


def _refine(definition: Draft, message: str, ids: NewId) -> Reply:  # noqa: C901, PLR0911, PLR0912, PLR0915
    next_definition = definition.model_copy(deep=True)
    output = next_definition.output

    def locate(phrase: str) -> Found | None:
        return _find_field(next_definition, phrase, message)

    def path(found: Found) -> str:
        record_type, index = found
        return f"{record_type.name} / {record_type.fields[index].name}"

    # rename X to Y
    if hit := re.search(r"\brename\s+(.+?)\s+to\s+(.+?)\s*[.!]?$", message, re.I):
        found = locate(hit[1])
        if not found:
            return _not_found(hit[1], next_definition)
        field = found[0].fields[found[1]]
        before = path(found)
        name = _clean_name(hit[2])
        field.name = name
        return _done(
            f'I renamed "{before}" to "{name}". Its key stays "{field.key}", '
            "so the template keeps working.",
            next_definition,
            [
                Reason(
                    path=before,
                    reason=f'Renamed to "{name}"; the key is unchanged so existing output keeps its shape.',
                )
            ],
        )

    # split A and B
    if hit := re.search(
        r"\bsplit\s+(?:the\s+)?(.+?)\s+and\s+(.+?)\s*[.!]?$", message, re.I
    ):
        a, b = _clean_name(hit[1]), _clean_name(hit[2])
        record_type = _target_type(next_definition, message)
        match = locate(hit[1]) or locate(hit[2])
        if not match:
            for index, candidate in enumerate(record_type.fields):
                if _shares_stem(candidate, hit[1]):
                    match = (record_type, index)
                    break
        owner = match[0] if match else record_type
        old = owner.fields[match[1]] if match else None
        taken = [f.key for f in owner.fields if f is not old]
        first = _make_field(
            a,
            ids,
            taken,
            mode=old.mode if old else "quote",
            multiple=old.multiple if old else False,
        )
        second = _make_field(
            b, ids, [*taken, first.key], mode=old.mode if old else "quote"
        )
        if old and match:
            owner.fields[match[1] : match[1] + 1] = [first, second]
        else:
            owner.fields.extend([first, second])
        if output.format == "markdown":
            if old:
                output.template = _remove_from_template(output.template, old)
            output.template = _append_to_template(
                _append_to_template(output.template, first), second
            )
        reasons: list[Reason] = []
        if old:
            reasons.append(
                Reason(
                    path=f"{owner.name} / {old.name}",
                    reason="Replaced by two separate fields.",
                )
            )
        for name in (a, b):
            reasons.append(
                Reason(
                    path=f"{owner.name} / {name}",
                    reason="Gets its own field so it can be checked on its own.",
                )
            )
        return _done(
            f'I replaced "{old.name}" with two fields, "{a}" and "{b}".'
            if old
            else f'There was no single field to split, so I added two: "{a}" and "{b}".',
            next_definition,
            reasons,
        )

    # X can have several values
    if hit := re.search(
        r"^\s*(?:the\s+)?(.+?)\s+can\s+have\s+(?:several|multiple|many|more than one)\s+values?",
        message,
        re.I,
    ):
        found = locate(hit[1])
        if not found:
            return _not_found(hit[1], next_definition)
        field = found[0].fields[found[1]]
        field.multiple = True
        if output.format == "markdown":
            key = re.escape(field.key)
            labelled = re.compile(
                rf"^(\*\*[^*\n]+:\*\*)[ \t]*\{{\{{{key}\}}\}}[ \t]*$", re.M
            )
            alone = re.compile(rf"^[ \t]*\{{\{{{key}\}}\}}[ \t]*$", re.M)
            k = field.key
            listing = f"{{{{#{k}}}}}- {{{{.}}}}\n{{{{/{k}}}}}"
            template = output.template
            if labelled.search(template):
                output.template = labelled.sub(
                    lambda m: f"{m[1]}\n{listing}", template, count=1
                )
            else:
                output.template = alone.sub(lambda _m: listing, template, count=1)
        return _done(
            f'"{field.name}" can now hold several values.',
            next_definition,
            [
                Reason(
                    path=path(found),
                    reason="A record can have more than one of these, so each is listed on its own.",
                )
            ],
        )

    # make X exact / inferred
    if hit := re.search(
        r"\bmake\s+(.+?)\s+(?:be\s+|an?\s+)?(exact|quote|quoted|verbatim|inferred)\b",
        message,
        re.I,
    ):
        found = locate(hit[1])
        if not found:
            return _not_found(hit[1], next_definition)
        field = found[0].fields[found[1]]
        field.mode = "inferred" if re.search("inferred", hit[2], re.I) else "quote"
        if field.mode == "quote":
            text = f'"{field.name}" is now copied exactly from the text.'
            reason = "Copied word for word, so the value always matches the document."
        else:
            text = (
                f'"{field.name}" is now worked out by the model, '
                "with the passages it used as evidence."
            )
            reason = "Worked out from the text, which suits values that are not written down as such."
        return _done(text, next_definition, [Reason(path=path(found), reason=reason)])

    # output as json / csv / markdown
    if hit := re.search(
        r"\b(?:output|export|format|write)\b.*?\b(json|csv|markdown)\b", message, re.I
    ):
        output_format = hit[1].lower()
        output.format = output_format  # type: ignore[assignment]
        if output_format == "markdown" and not output.template.strip():
            record_types = next_definition.record_types
            output.template = _template_for(record_types[0]) if record_types else ""
        return _done(
            f"The output is now {output_format}.",
            next_definition,
            [Reason(path="Output", reason=f"Records are written as {output_format}.")],
        )

    # use / add X in the template
    if hit := re.search(
        r"\b(?:use|add|include|put)\s+(.+?)\s+(?:in|to|into|on)\s+(?:the\s+)?template\b",
        message,
        re.I,
    ):
        found = locate(hit[1])
        if not found:
            return _not_found(hit[1], next_definition)
        field = found[0].fields[found[1]]
        before = output.template
        output.template = _append_to_template(before, field)
        if output.template == before:
            return _nothing(f'"{field.name}" is already in the template.')
        return _done(
            f'I added "{field.name}" to the template.',
            next_definition,
            [Reason(path="Template", reason=f'Shows "{field.name}" for each record.')],
        )

    # add (a field for) X
    if hit := re.search(
        r"\badd\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?(?:field\s+)?(?:for\s+|called\s+|named\s+)?(.+?)\s*[.!]?$",
        message,
        re.I,
    ):
        name = _clean_name(
            re.split(
                r"\s+(?:to|on|in|as|that|which|and derive|and normali[sz]e|,)\b|,",
                hit[1],
                flags=re.I,
            )[0]
        )
        if not name:
            return _nothing("I couldn't tell which field to add.")
        record_type = _target_type(next_definition, message)
        key = key_from_name(name)
        if any(f.key == key for f in record_type.fields):
            return _nothing(f'"{record_type.name}" already has a field "{name}".')
        mode = _mode_of(message)
        field = _make_field(name, ids, [f.key for f in record_type.fields], mode=mode)
        record_type.fields.append(field)
        markdown = output.format == "markdown"
        if markdown:
            output.template = _append_to_template(output.template, field)
        how = (
            "copied exactly from the text"
            if mode == "quote"
            else "worked out from the text"
        )
        reasons = [
            Reason(
                path=f"{record_type.name} / {name}",
                reason=(
                    "New field, copied exactly from the document."
                    if mode == "quote"
                    else "New field, worked out from the document."
                ),
            )
        ]
        if markdown:
            reasons.append(
                Reason(path="Template", reason=f'Shows "{name}" for each record.')
            )
        return _done(
            f'I added "{name}" to {record_type.name}, {how}.'
            f"{' It is in the template too.' if markdown else ''}",
            next_definition,
            reasons,
        )

    # remove / drop X
    if hit := re.search(
        r"\b(?:remove|drop|delete)\s+(.+?)(?:\s+from\s+.+?)?\s*[.!]?$", message, re.I
    ):
        found = locate(hit[1])
        if not found:
            return _not_found(hit[1], next_definition)
        record_type, index = found
        field = record_type.fields.pop(index)
        output.template = _remove_from_template(output.template, field)
        return _done(
            f'I removed "{field.name}" from {record_type.name} and from the template.',
            next_definition,
            [
                Reason(
                    path=f"{record_type.name} / {field.name}",
                    reason="Removed, as you asked.",
                ),
                Reason(path="Template", reason=f'No longer shows "{field.name}".'),
            ],
        )

    return _nothing("I didn't understand that one.")


def _normalise(definition: Draft) -> Draft:
    """Every proposal is a complete draft: keys filled and unique, choice fields with choices.

    The result goes through the models once more, so strings are trimmed as in a saved draft.
    """
    for record_type in definition.record_types:
        seen: list[str] = []
        for field in record_type.fields:
            field.key = _unique_key(field.key or field.name, seen)
            seen.append(field.key)
            if field.value_type == "choice" and not field.choices:
                field.choices = ["other"]
    return Draft.model_validate(definition.model_dump())


def assistant_reply(text: str, definition: Draft, ids: NewId = new_id) -> Reply:
    """The whole reply: its text and at most one proposal. ``definition`` is not changed."""
    message = text.strip()
    if not definition.record_types:
        reply = _propose(definition, message, ids)
    else:
        reply = _refine(definition, message, ids)
    if reply.proposal:
        return Reply(
            reply.text,
            Proposal(
                definition=_normalise(reply.proposal.definition),
                reasons=reply.proposal.reasons,
            ),
        )
    return reply


def split_into_deltas(text: str, words_per_delta: int = 3) -> list[str]:
    """Pieces of ``text`` that join to exactly ``text``, a few words each."""
    words = re.split(r"(?<=\s)(?=\S)", text)
    return [
        "".join(words[start : start + words_per_delta])
        for start in range(0, len(words), words_per_delta)
    ]


class ScriptedAgent:
    """Answers from the script above. ``ids`` makes the ids of new things; tests pass their own."""

    def __init__(self, ids: NewId = new_id) -> None:
        self._ids = ids

    async def reply(
        self,
        text: str,
        definition: Draft,
        history: list[Message],
        workspace: Workspace,
    ) -> AsyncIterator[AgentEvent]:
        reply = assistant_reply(text, definition, self._ids)
        for piece in split_into_deltas(reply.text):
            yield TextDelta(piece)
        if reply.proposal:
            yield reply.proposal
