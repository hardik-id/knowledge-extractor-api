"""Permission helpers. See docs/permissions.md.

A selector takes the acting user and returns only rows that user may see. These
helpers sit on top: a row that is not visible does not exist (404), a row that is
visible but may not be changed answers 403.
"""

from typing import Any, Protocol

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Model

from apps.core.errors import ApiError


class Changeable(Protocol):
    def can_be_changed_by(self, user: Any) -> bool: ...


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


def require_can_change(obj: Changeable, user: Any) -> None:
    """Raise 403 ``forbidden`` unless ``user`` may change ``obj``.

    Call it only on a row already fetched with ``get_visible_or_404``.
    """
    if not obj.can_be_changed_by(user):
        raise ApiError("forbidden")
