from django.db import migrations


def assign_database_owners(apps, schema_editor):
    ResearchDatabase = apps.get_model('research', 'ResearchDatabase')
    DatabaseMembership = apps.get_model('research', 'DatabaseMembership')

    for database in ResearchDatabase.objects.all().iterator():
        owner_membership = DatabaseMembership.objects.filter(
            research_database=database,
            role='owner',
        ).first()
        if owner_membership:
            continue

        creator_membership, _ = DatabaseMembership.objects.get_or_create(
            research_database=database,
            user_id=database.created_by_id,
            defaults={'role': 'owner'},
        )
        if creator_membership.role != 'owner':
            creator_membership.role = 'owner'
            creator_membership.save(update_fields=['role'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('research', '0007_alter_databasemembership_role'),
    ]

    operations = [
        migrations.RunPython(assign_database_owners, noop_reverse),
    ]
