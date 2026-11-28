import io
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.iam.models import AuditEntry, PlatformAdmin
from apps.iam.tests.factories import PlatformAdminFactory
from apps.identity.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def run(*args: str) -> str:
    out = io.StringIO()
    call_command("platform_admin", *args, stdout=out)
    return out.getvalue()


def test_grant_list_and_revoke() -> None:
    other, person = PlatformAdminFactory().user, UserFactory()
    run("grant", "--oid", str(person.oid))
    assert str(person.oid) in run("list")
    assert PlatformAdmin.objects.filter(user=person).exists()
    run("revoke", "--oid", str(person.oid))
    assert not PlatformAdmin.objects.filter(user=person).exists()
    assert AuditEntry.objects.filter(actor__isnull=True).count() == 2
    assert other


def test_list_shows_the_setting(settings: Any) -> None:
    person = UserFactory()
    settings.IAM_PLATFORM_ADMIN_OIDS = frozenset({person.oid})
    assert f"{person.oid}\tsetting" in run("list")


def test_an_oid_that_never_signed_in_is_refused() -> None:
    with pytest.raises(CommandError, match="signed in"):
        run("grant", "--oid", "de000000-0000-4000-8000-0000000000ff")


def test_the_last_platform_admin_is_refused() -> None:
    row = PlatformAdminFactory()
    with pytest.raises(CommandError, match="last"):
        run("revoke", "--oid", str(row.user.oid))
