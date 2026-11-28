import pytest


@pytest.fixture(autouse=True)
def _default_tenant(request: pytest.FixtureRequest) -> None:
    """The migration makes the Default tenant, but a transactional test (the
    migration test) flushes it. Every other test gets it back here, so none
    depends on the order the tests run in."""
    if request.node.get_closest_marker("django_db") is None:
        return
    marker = request.node.get_closest_marker("django_db")
    if marker.kwargs.get("transaction"):
        return
    request.getfixturevalue("db")
    from apps.iam.models import Tenant

    Tenant.objects.get_or_create(is_default=True, defaults={"name": "Default"})
