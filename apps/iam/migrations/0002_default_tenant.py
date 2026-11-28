import uuid

from django.db import migrations


def create_default_tenant(apps, schema_editor):  # type: ignore[no-untyped-def]
    Tenant = apps.get_model("iam", "Tenant")
    Membership = apps.get_model("iam", "TenantMembership")
    User = apps.get_model("identity", "User")
    tenant, _ = Tenant.objects.get_or_create(
        is_default=True, defaults={"name": "Default"}
    )
    have = set(Membership.objects.filter(tenant=tenant).values_list("user_id", flat=True))
    Membership.objects.bulk_create(
        [
            Membership(id=uuid.uuid7(), tenant=tenant, user_id=pk, role="member")
            for pk in User.objects.values_list("pk", flat=True)
            if pk not in have
        ]
    )


def remove_default_tenant(apps, schema_editor):  # type: ignore[no-untyped-def]
    apps.get_model("iam", "Tenant").objects.filter(is_default=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("iam", "0001_tenants_roles_audit"),
        ("identity", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_default_tenant, remove_default_tenant)]
