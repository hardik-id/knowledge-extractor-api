from apps.identity.tests.factories import UserFactory


def test_user_factory_builds_distinct_users(db):
    first, second = UserFactory(), UserFactory()
    assert first.pk != second.pk
    assert (first.oid, first.tid) != (second.oid, second.tid)


def test_user_fixture_is_saved(user):
    assert user.pk is not None


def test_api_client_fixture_is_unauthenticated(api_client):
    assert api_client.handler._force_user is None
