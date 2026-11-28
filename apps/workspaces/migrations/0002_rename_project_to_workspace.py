from django.db import migrations, models


class Migration(migrations.Migration):
    """Project becomes Workspace. The rows stay where they are, with the same ids."""

    dependencies = [
        ("projects", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel(old_name="Project", new_name="Workspace"),
        migrations.AlterModelTable(name="workspace", table="workspaces_workspace"),
        migrations.AlterField(
            model_name="workspace",
            name="run",
            field=models.OneToOneField(
                on_delete=models.PROTECT, related_name="workspace", to="runs.run"
            ),
        ),
    ]
