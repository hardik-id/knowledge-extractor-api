"""``@requires``: a declaration that does not fit its view stops the app at start."""

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.iam.roles import Permission
from apps.iam.routes import APPLICATION_PERMISSIONS, OPEN, SIGNED_IN, requires


def _view() -> Any:
    @api_view(["GET", "POST"])
    def view(request: Request) -> Response:
        return Response()

    return view


def test_every_method_is_declared_and_no_other() -> None:
    with pytest.raises(ImproperlyConfigured, match="declare exactly"):
        requires(GET=SIGNED_IN)(_view())
    with pytest.raises(ImproperlyConfigured, match="declare exactly"):
        requires(GET=SIGNED_IN, POST=SIGNED_IN, DELETE=SIGNED_IN)(_view())
    view = requires(GET=SIGNED_IN, POST=Permission.WORKSPACE_EDIT)(_view())
    assert view.cls.needs == {"GET": SIGNED_IN, "POST": Permission.WORKSPACE_EDIT}


def test_a_value_is_a_permission_signed_in_or_open() -> None:
    with pytest.raises(ImproperlyConfigured, match="not a permission"):
        requires(GET="workspace.read", POST=SIGNED_IN)(_view())


def test_a_view_is_open_on_all_its_methods_or_on_none() -> None:
    with pytest.raises(ImproperlyConfigured, match="open on all"):
        requires(GET=OPEN, POST=SIGNED_IN)(_view())


def test_it_goes_above_api_view() -> None:
    def plain(request: Request) -> Response:
        return Response()

    with pytest.raises(ImproperlyConfigured, match="above @api_view"):
        requires(GET=SIGNED_IN)(plain)


def test_the_application_permissions_are_the_platform_admins_own() -> None:
    assert APPLICATION_PERMISSIONS == {
        Permission.STATUS_TEST,
        Permission.TENANTS_MANAGE,
        Permission.USERS_LIST,
    }
