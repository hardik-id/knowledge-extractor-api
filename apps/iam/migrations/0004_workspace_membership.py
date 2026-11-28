import uuid

import django.db.models.deletion
import django.db.models.functions
from django.conf import settings
from django.db import migrations, models


def owners_become_owner(apps, schema_editor):  # type: ignore[no-untyped-def]
    Workspace = apps.get_model("projects", "Workspace")
    Membership = apps.get_model("iam", "WorkspaceMembership")
    Membership.objects.bulk_create(
        [
            Membership(id=uuid.uuid7(), workspace_id=pk, user_id=owner_id, role="owner")
            for pk, owner_id in Workspace.objects.values_list("pk", "owner_id")
        ]
    )


class Migration(migrations.Migration):
    """Every existing workspace gets its owner as `owner`."""

    dependencies = [
        ("iam", "0003_audit_identity"),
        ("projects", "0003_workspace_tenant"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkspaceMembership",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("owner", "owner"),
                            ("editor", "editor"),
                            ("viewer", "viewer"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="projects.workspace",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace", "user"),
                        name="iam_workspace_membership_unique",
                    )
                ],
            },
        ),
        migrations.RunPython(owners_become_owner, migrations.RunPython.noop),
    ]
