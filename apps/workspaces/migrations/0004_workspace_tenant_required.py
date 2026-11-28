import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0003_workspace_tenant")]

    operations = [
        migrations.AlterField(
            model_name="workspace",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workspaces",
                to="iam.tenant",
            ),
        ),
    ]
