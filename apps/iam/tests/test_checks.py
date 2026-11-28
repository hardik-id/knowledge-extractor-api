import uuid
from typing import Any

import pytest

from apps.iam.checks import platform_admin_exists
from apps.iam.tests.factories import PlatformAdminFactory

pytestmark = pytest.mark.django_db


def test_warns_in_production_when_nobody_is_a_platform_admin(settings: Any) -> None:
    settings.AUTH_MODE = "entra"
    settings.IAM_PLATFORM_ADMIN_OIDS = frozenset()
    (warning,) = platform_admin_exists()
    assert warning.id == "iam.W001"


def test_quiet_with_a_listed_oid_a_row_or_in_dev(settings: Any) -> None:
    settings.AUTH_MODE = "entra"
    settings.IAM_PLATFORM_ADMIN_OIDS = frozenset({uuid.uuid4()})
    assert platform_admin_exists() == []
    settings.IAM_PLATFORM_ADMIN_OIDS = frozenset()
    PlatformAdminFactory()
    assert platform_admin_exists() == []


def test_quiet_in_dev_mode(settings: Any) -> None:
    settings.AUTH_MODE = "dev"
    settings.IAM_PLATFORM_ADMIN_OIDS = frozenset()
    assert platform_admin_exists() == []
