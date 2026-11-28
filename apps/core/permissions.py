"""Visibility helper. See docs/permissions.md.

A selector takes the acting user and returns only rows that user may see. A row
that is not visible does not exist (404). What a person may do with a row they see
is their role's permission, checked by the selector of that row (docs/iam.md).
"""

from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Model

from apps.core.errors import ApiError


def get_visible_or_404[M: Model](
    model: type[M], user: Any, pk: Any, *, code: str = "not_found"
) -> M:
    """The row ``pk`` if ``user`` may see it, otherwise ``ApiError(code)``.

    ``model.objects`` must have ``visible_to`` (an ``OwnedModel`` does). A missing row and
    somebody else's row raise the same error, so the answer never tells them apart.
    A malformed id is a missing row too.
    """
    try:
        return model.objects.visible_to(user).get(pk=pk)  # type: ignore[attr-defined, no-any-return]
    except ObjectDoesNotExist, ValidationError, ValueError, TypeError:
        raise ApiError(code) from None
