import django.db.models.deletion
from django.db import migrations, models


def put_in_default(apps, schema_editor):  # type: ignore[no-untyped-def]
    Tenant = apps.get_model("iam", "Tenant")
    Workspace = apps.get_model("projects", "Workspace")
    default, _ = Tenant.objects.get_or_create(
        is_default=True, defaults={"name": "Default"}
    )
    Workspace.objects.filter(tenant__isnull=True).update(tenant=default)


class Migration(migrations.Migration):
    """Every existing workspace goes to the tenant "Default"."""

    dependencies = [
        ("projects", "0002_rename_project_to_workspace"),
        ("iam", "0003_audit_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="tenant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workspaces",
                to="iam.tenant",
            ),
        ),
        migrations.RunPython(put_in_default, migrations.RunPython.noop),
    ]
