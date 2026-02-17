import uuid

from django.db import migrations, models


def populate_organization_uuids(apps, schema_editor):
    Organization = apps.get_model('research', 'Organization')
    for organization in Organization.objects.filter(uuid__isnull=True):
        organization.uuid = uuid.uuid4()
        organization.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('research', '0018_userprofile'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='uuid',
            field=models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.RunPython(populate_organization_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='organization',
            name='uuid',
            field=models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
