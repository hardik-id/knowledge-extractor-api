"""One small checker per message, mirroring what the UI's parser requires.

The UI's `src/services/http/parsers.ts` is the contract: a message that fails
there breaks the app. Each checker here asks the same of a message, at the same
paths, and fails with the path of the first thing wrong, for example
``extraction.records[0].file_id: expected text``. Written once, used at every
step of the flow test.
"""

from collections.abc import Callable
from typing import Any, NoReturn

SOURCES = ("confluence", "sharepoint", "upload", "storage")
FILE_TYPES = ("pdf", "docx", "xlsx", "pptx", "html", "md", "txt")
WORK_STAGES = ("ingest", "transform", "classify", "enrich", "extract", "index")
CELL_STATUSES = ("pending", "queued", "running", "succeeded", "failed", "stale")
FIELD_MODES = ("quote", "inferred")
FIELD_VALUE_TYPES = ("text", "date", "number", "choice")
OUTPUT_FORMATS = ("json", "markdown", "csv")
REVIEW_STATES = ("suggested", "accepted", "rejected")
ORIGINS = ("llm", "human")
ROLES = ("user", "assistant")
MESSAGE_STATUSES = ("streaming", "done")


def invalid(path: str, expected: str) -> NoReturn:
    raise AssertionError(f"The UI would reject this: {path}: expected {expected}")


def obj(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        invalid(path, "an object")
    return value


def array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        invalid(path, "a list")
    return value


def string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        invalid(path, "text")
    return value


def number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        invalid(path, "a number")
    return value


def boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        invalid(path, "true or false")
    return value


def one_of(value: Any, options: tuple[str, ...], path: str) -> str:
    if not isinstance(value, str) or value not in options:
        invalid(path, f"one of {', '.join(options)}")
    return value


def nullable(value: Any, check: Callable[[Any], Any]) -> None:
    if value is not None:
        check(value)


def check_file(value: Any, path: str = "file") -> None:
    o = obj(value, path)
    string(o.get("id"), f"{path}.id")
    string(o.get("name"), f"{path}.name")
    one_of(o.get("source"), SOURCES, f"{path}.source")
    one_of(o.get("type"), FILE_TYPES, f"{path}.type")
    number(o.get("size_bytes"), f"{path}.size_bytes")
    string(o.get("location"), f"{path}.location")
    string(o.get("modified_at"), f"{path}.modified_at")
    nullable(o.get("etag"), lambda v: string(v, f"{path}.etag"))


def check_files(value: Any) -> None:
    items = array(obj(value, "response").get("items"), "items")
    for i, item in enumerate(items):
        check_file(item, f"items[{i}]")


def check_cell(value: Any, path: str = "cell") -> None:
    o = obj(value, path)
    one_of(o.get("stage"), WORK_STAGES, f"{path}.stage")
    string(o.get("file_id"), f"{path}.file_id")
    one_of(o.get("status"), CELL_STATUSES, f"{path}.status")
    nullable(o.get("execution_id"), lambda v: string(v, f"{path}.execution_id"))
    nullable(o.get("progress"), lambda v: number(v, f"{path}.progress"))

    def error(v: Any) -> None:
        e = obj(v, f"{path}.error")
        string(e.get("code"), f"{path}.error.code")
        string(e.get("message"), f"{path}.error.message")

    def output(v: Any) -> None:
        out = obj(v, f"{path}.output")
        string(out.get("name"), f"{path}.output.name")
        string(out.get("content_type"), f"{path}.output.content_type")
        number(out.get("size"), f"{path}.output.size")
        string(out.get("etag"), f"{path}.output.etag")

    nullable(o.get("error"), error)
    nullable(o.get("output"), output)
    string(o.get("updated_at"), f"{path}.updated_at")


def check_run(value: Any) -> None:
    o = obj(value, "run")
    string(o.get("id"), "run.id")
    string(o.get("created_at"), "run.created_at")
    for i, f in enumerate(array(o.get("files"), "run.files")):
        check_file(f, f"run.files[{i}]")
    for i, c in enumerate(array(o.get("cells"), "run.cells")):
        check_cell(c, f"run.cells[{i}]")


def check_execution(value: Any) -> None:
    o = obj(value, "execution")
    string(o.get("execution_id"), "execution.execution_id")
    one_of(o.get("stage"), WORK_STAGES, "execution.stage")
    for i, id_ in enumerate(array(o.get("file_ids"), "execution.file_ids")):
        string(id_, f"execution.file_ids[{i}]")


def _field_def(value: Any, path: str) -> None:
    o = obj(value, path)
    for key in ("id", "key", "name", "description"):
        string(o.get(key), f"{path}.{key}")
    one_of(o.get("mode"), FIELD_MODES, f"{path}.mode")
    one_of(o.get("value_type"), FIELD_VALUE_TYPES, f"{path}.value_type")
    if o.get("choices") is not None:
        for i, c in enumerate(array(o["choices"], f"{path}.choices")):
            string(c, f"{path}.choices[{i}]")
    boolean(o.get("multiple"), f"{path}.multiple")


def _record_type(value: Any, path: str) -> None:
    o = obj(value, path)
    for key in ("id", "name", "description"):
        string(o.get(key), f"{path}.{key}")
    for i, f in enumerate(array(o.get("fields"), f"{path}.fields")):
        _field_def(f, f"{path}.fields[{i}]")


def check_definition_body(value: Any, path: str = "definition") -> None:
    o = obj(value, path)
    string(o.get("prompt"), f"{path}.prompt")
    for i, t in enumerate(array(o.get("record_types"), f"{path}.record_types")):
        _record_type(t, f"{path}.record_types[{i}]")
    output = obj(o.get("output"), f"{path}.output")
    one_of(output.get("format"), OUTPUT_FORMATS, f"{path}.output.format")
    string(output.get("template"), f"{path}.output.template")


def check_definition(value: Any) -> None:
    number(obj(value, "definition").get("version"), "definition.version")
    check_definition_body(value)


def _span(value: Any, path: str) -> None:
    o = obj(value, path)
    number(o.get("start"), f"{path}.start")
    number(o.get("end"), f"{path}.end")
    string(o.get("quote"), f"{path}.quote")


def _field_value(value: Any, path: str) -> None:
    o = obj(value, path)
    string(o.get("id"), f"{path}.id")
    string(o.get("field_id"), f"{path}.field_id")
    nullable(o.get("value"), lambda v: string(v, f"{path}.value"))
    for i, s in enumerate(array(o.get("spans"), f"{path}.spans")):
        _span(s, f"{path}.spans[{i}]")
    one_of(o.get("origin"), ORIGINS, f"{path}.origin")
    one_of(o.get("review"), REVIEW_STATES, f"{path}.review")
    boolean(o.get("anchored"), f"{path}.anchored")


def _record(value: Any, path: str) -> None:
    o = obj(value, path)
    string(o.get("id"), f"{path}.id")
    string(o.get("file_id"), f"{path}.file_id")
    string(o.get("record_type_id"), f"{path}.record_type_id")
    nullable(o.get("span"), lambda v: _span(v, f"{path}.span"))
    for i, f in enumerate(array(o.get("fields"), f"{path}.fields")):
        _field_value(f, f"{path}.fields[{i}]")
    one_of(o.get("origin"), ORIGINS, f"{path}.origin")
    one_of(o.get("review"), REVIEW_STATES, f"{path}.review")
    boolean(o.get("use_as_example"), f"{path}.use_as_example")


def check_extraction(value: Any) -> None:
    o = obj(value, "extraction")
    string(o.get("file_id"), "extraction.file_id")
    number(o.get("revision"), "extraction.revision")
    string(o.get("source_etag"), "extraction.source_etag")
    number(o.get("definition_version"), "extraction.definition_version")
    for i, r in enumerate(array(o.get("records"), "extraction.records")):
        _record(r, f"extraction.records[{i}]")


def check_proposal(value: Any, path: str = "proposal") -> None:
    o = obj(value, path)
    check_definition_body(o.get("definition"), f"{path}.definition")
    if o.get("reasons") is not None:
        for i, r in enumerate(array(o["reasons"], f"{path}.reasons")):
            reason = obj(r, f"{path}.reasons[{i}]")
            string(reason.get("path"), f"{path}.reasons[{i}].path")
            string(reason.get("reason"), f"{path}.reasons[{i}].reason")


def check_assistant_message(value: Any, path: str = "message") -> None:
    o = obj(value, path)
    string(o.get("id"), f"{path}.id")
    one_of(o.get("role"), ROLES, f"{path}.role")
    string(o.get("text"), f"{path}.text")
    nullable(o.get("proposal"), lambda v: check_proposal(v, f"{path}.proposal"))
    one_of(o.get("status"), MESSAGE_STATUSES, f"{path}.status")
    string(o.get("created_at"), f"{path}.created_at")


def check_assistant_messages(value: Any) -> None:
    for i, m in enumerate(array(obj(value, "response").get("messages"), "messages")):
        check_assistant_message(m, f"messages[{i}]")


# --- socket messages ------------------------------------------------------


def check_cell_message(value: Any) -> None:
    o = obj(value, "message")
    one_of(o.get("type"), ("cell",), "message.type")
    check_cell(o.get("cell"), "message.cell")


def check_extraction_changed_message(value: Any) -> None:
    o = obj(value, "message")
    one_of(o.get("type"), ("extraction.changed",), "message.type")
    string(o.get("file_id"), "message.file_id")
    number(o.get("revision"), "message.revision")


def check_assistant_event(value: Any) -> None:
    o = obj(value, "message")
    kind = one_of(
        o.get("type"),
        ("assistant.delta", "assistant.proposal", "assistant.done"),
        "message.type",
    )
    string(o.get("message_id"), "message.message_id")
    if kind == "assistant.delta":
        string(o.get("text"), "message.text")
    if kind == "assistant.proposal":
        check_proposal(o.get("proposal"), "message.proposal")


def check_socket_message(value: Any) -> None:
    """Whatever the run socket may send, checked as the UI's parser for its type."""
    kind = obj(value, "message").get("type")
    if kind == "cell":
        check_cell_message(value)
    elif kind == "extraction.changed":
        check_extraction_changed_message(value)
    else:
        check_assistant_event(value)
