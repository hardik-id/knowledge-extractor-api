import pytest

from apps.core.errors import ApiError
from apps.identity.tests.factories import UserFactory
from apps.runs import selectors, services
from apps.runs.models import CellStatus
from apps.runs.tests.factories import CellFactory, RunFileFactory

pytestmark = pytest.mark.django_db


def test_set_cell_changes_it_and_moves_updated_at() -> None:
    cell = CellFactory()
    before = cell.updated_at
    out = {"name": "a.md", "content_type": "text/markdown", "size": 3, "etag": "e"}
    changed = services.set_cell(
        cell.file,
        "extract",
        status="succeeded",
        execution_id="x1",
        progress=100,
        output=out,
    )
    cell.refresh_from_db()
    assert cell.status == CellStatus.SUCCEEDED
    assert (cell.execution_id, cell.progress, cell.output) == ("x1", 100, out)
    assert cell.updated_at > before
    assert changed.updated_at == cell.updated_at


def test_set_cell_records_an_error() -> None:
    cell = CellFactory()
    services.set_cell(
        cell.file, "extract", status="failed", error={"code": "x", "message": "m"}
    )
    cell.refresh_from_db()
    assert cell.error == {"code": "x", "message": "m"}


def test_get_run_file() -> None:
    file = RunFileFactory()
    owner = file.run.owner
    assert selectors.get_run_file(owner, file.run_id, file.pk) == file
    with pytest.raises(ApiError) as missing:
        selectors.get_run_file(owner, file.run_id, RunFileFactory().pk)
    assert missing.value.code == "file_not_found"
    with pytest.raises(ApiError) as other:
        selectors.get_run_file(UserFactory(), file.run_id, file.pk)
    assert other.value.code == "run_not_found"
