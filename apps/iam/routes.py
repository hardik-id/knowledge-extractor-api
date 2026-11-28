"""What each route needs: declared on its view, per HTTP method, in one place.

Every view under ``/api/v1`` carries ``@requires(...)`` above ``@api_view``, one
keyword per method it answers::

    @requires(GET=Permission.WORKSPACE_VIEW, PUT=Permission.WORKSPACE_EDIT)
    @api_view(["GET", "PUT"])
    def definition(request, run_id): ...

A value is a ``Permission`` of ``roles.py``, ``SIGNED_IN`` or ``OPEN``. Who checks it:

- ``OPEN``: nobody; the route needs no sign-in.
- ``SIGNED_IN``: a signed-in person. A service may check more (the tenant of a new
  workspace).
- an application permission (``status.test``, ``tenants.manage``, ``users.list``):
  checked here, before the view runs: a platform admin, otherwise 403 ``forbidden``.
- a workspace or tenant permission: the function that fetches the row, given the
  permission (``runs.get_run(user, run_id, permission)``), so that a hidden row is
  404 before a refused one is 403. Here it only needs a signed-in person.

The route sweep (``apps/iam/tests/test_route_sweep.py``) fails for a route that
declares nothing and checks every declaration against real roles. docs/iam.md.
"""

from collections.abc import Callable
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.request import Request

from .roles import PERMISSIONS, Permission, PlatformAdminRole
from .selectors import is_platform_admin

OPEN: Final = "open"
SIGNED_IN: Final = "signed_in"

# Held by platform admins and no other role: they need no row to be checked against.
APPLICATION_PERMISSIONS: frozenset[Permission] = PERMISSIONS[
    PlatformAdminRole.PLATFORM_ADMIN
].difference(
    *(p for role, p in PERMISSIONS.items() if role != PlatformAdminRole.PLATFORM_ADMIN)
)

# Never declared: OPTIONS answers what a signed-in person may call, HEAD is a GET.
UNDECLARED_METHODS: Final = frozenset({"OPTIONS", "HEAD"})


def _need(value: str) -> str:
    if value in (OPEN, SIGNED_IN):
        return value
    try:
        return Permission(value)
    except ValueError:
        raise ImproperlyConfigured(
            f"{value!r} is not a permission, {SIGNED_IN!r} or {OPEN!r}."
        ) from None


def methods_of(view: Any) -> frozenset[str]:
    """The methods a view answers that need a declaration, upper case."""
    names = getattr(getattr(view, "cls", None), "http_method_names", ())
    return frozenset(m.upper() for m in names) - UNDECLARED_METHODS


def needs_of(view: Any) -> dict[str, str]:
    """The declaration of a view, by method; empty when it has none."""
    return dict(getattr(getattr(view, "cls", None), "needs", {}))


class Declared(BasePermission):
    """The DRF permission class of every declared view: applies its declaration."""

    def has_permission(self, request: Request, view: Any) -> bool:
        needs: dict[str, str] = view.needs
        method = "GET" if request.method == "HEAD" else request.method
        need = needs.get(str(method), SIGNED_IN)
        if need == OPEN:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False  # 401: DRF answers ``unauthenticated``
        if need in APPLICATION_PERMISSIONS:
            return is_platform_admin(user)  # False is 403 ``forbidden``
        return True


def requires[V: Callable[..., Any]](**needs: str) -> Callable[[V], V]:
    """Declare what each method of an ``@api_view`` needs. Put it above ``@api_view``.

    Every method the view answers is declared, and nothing else: a missing or an
    extra method stops the app at start.
    """
    checked = {method: _need(value) for method, value in needs.items()}

    def decorate(view: V) -> V:
        cls = getattr(view, "cls", None)
        if cls is None:
            raise ImproperlyConfigured(
                f"{view.__name__}: put @requires above @api_view."
            )
        if set(checked) != methods_of(view):
            raise ImproperlyConfigured(
                f"{view.__name__}: declare exactly {sorted(methods_of(view))}, "
                f"not {sorted(checked)}."
            )
        cls.needs = checked
        cls.permission_classes = [Declared]
        if set(checked.values()) == {OPEN}:
            # AllowAny also marks the route open in the OpenAPI schema.
            cls.authentication_classes = []
            cls.permission_classes = [AllowAny]
        elif OPEN in checked.values():
            raise ImproperlyConfigured(
                f"{view.__name__}: a view is open on all its methods or on none."
            )
        return view

    return decorate
