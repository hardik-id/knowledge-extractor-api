"""Writes and business rules for the extraction app.

A service takes the acting user as its first argument.
"""

from typing import Any

from django.db import IntegrityError, transaction

from apps.core.errors import ApiError
from apps.extraction import selectors
from apps.extraction.models import DefinitionVersion
from apps.extraction.validation import validate_draft
from apps.identity.models import User


def save_definition(
    user: User, run_id: Any, *, base_version: int, data: Any
) -> DefinitionVersion:
    """Save ``data`` as the next version, if ``base_version`` is still the latest.

    Otherwise 409 ``definition_conflict``. Two saves on the same base cannot both
    succeed: the database refuses a second row for one version number.
    """
    current = selectors.get_definition(user, run_id)
    draft = validate_draft(data)
    if base_version != current.version:
        raise _conflict(current.version)
    try:
        with transaction.atomic():
            return DefinitionVersion.objects.create(
                run_id=current.run_id, version=current.version + 1, **draft
            )
    except IntegrityError:
        latest = selectors.latest_version(current.run_id)
        raise _conflict(latest.version if latest else current.version) from None


def _conflict(version: int) -> ApiError:
    return ApiError(
        "definition_conflict",
        "Someone saved a newer version of this definition.",
        {"version": version},
    )
