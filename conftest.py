from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.identity.tests.factories import UserFactory


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db: None) -> Any:
    return UserFactory()
