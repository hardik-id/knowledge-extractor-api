import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class UserModelTests(TestCase):
    def test_auth_user_model_is_identity_user(self) -> None:
        self.assertEqual(User._meta.label, "identity.User")

    def test_same_oid_and_tid_refused(self) -> None:
        oid, tid = uuid.uuid4(), uuid.uuid4()
        User.objects.create(username="a", oid=oid, tid=tid)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create(username="b", oid=oid, tid=tid)

    def test_same_oid_in_another_tenant_allowed(self) -> None:
        oid = uuid.uuid4()
        User.objects.create(username="a", oid=oid, tid=uuid.uuid4())
        User.objects.create(username="b", oid=oid, tid=uuid.uuid4())

    def test_several_local_accounts_without_identity(self) -> None:
        User.objects.create(username="a")
        User.objects.create(username="b")
        self.assertEqual(
            User.objects.filter(oid__isnull=True, tid__isnull=True).count(), 2
        )

    def test_display_fields_are_not_unique(self) -> None:
        User.objects.create(username="a", name="Ada", preferred_username="ada@x.com")
        User.objects.create(username="b", name="Ada", preferred_username="ada@x.com")


class AdminTests(TestCase):
    def test_superuser_sees_user_list(self) -> None:
        User.objects.create_superuser("root", password="pw-for-tests")
        self.client.login(username="root", password="pw-for-tests")
        response = self.client.get(reverse("admin:identity_user_changelist"))
        self.assertContains(response, "root")
