from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('research', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='databasemembership',
            old_name='database',
            new_name='research_database',
        ),
        migrations.RenameField(
            model_name='organism',
            old_name='database',
            new_name='research_database',
        ),
        migrations.RenameField(
            model_name='location',
            old_name='database',
            new_name='research_database',
        ),
        migrations.RenameField(
            model_name='plasmid',
            old_name='database',
            new_name='research_database',
        ),
        migrations.RenameField(
            model_name='strain',
            old_name='database',
            new_name='research_database',
        ),
        migrations.RenameField(
            model_name='file',
            old_name='database',
            new_name='research_database',
        ),
        migrations.AlterModelOptions(
            name='databasemembership',
            options={'ordering': ['research_database__name', 'user__username']},
        ),
        migrations.AlterUniqueTogether(
            name='databasemembership',
            unique_together={('user', 'research_database')},
        ),
        migrations.AlterUniqueTogether(
            name='organism',
            unique_together={('research_database', 'name')},
        ),
        migrations.AlterUniqueTogether(
            name='location',
            unique_together={('research_database', 'building', 'room', 'freezer', 'box', 'position')},
        ),
        migrations.AlterUniqueTogether(
            name='plasmid',
            unique_together={('research_database', 'name')},
        ),
        migrations.AlterUniqueTogether(
            name='strain',
            unique_together={('research_database', 'strain_id')},
        ),
        migrations.AlterField(
            model_name='databasemembership',
            name='role',
            field=models.CharField(choices=[('admin', 'Admin'), ('editor', 'Editor'), ('viewer', 'Viewer')], default='viewer', max_length=20, db_index=True),
        ),
        migrations.AlterField(
            model_name='researchdatabase',
            name='name',
            field=models.CharField(max_length=200, db_index=True),
        ),
        migrations.AlterField(
            model_name='organism',
            name='name',
            field=models.CharField(max_length=200, db_index=True),
        ),
        migrations.AlterField(
            model_name='plasmid',
            name='name',
            field=models.CharField(max_length=150, db_index=True),
        ),
        migrations.AlterField(
            model_name='plasmid',
            name='resistance_marker',
            field=models.CharField(max_length=150, db_index=True),
        ),
        migrations.AlterField(
            model_name='strain',
            name='strain_id',
            field=models.CharField(max_length=60, db_index=True),
        ),
        migrations.AlterField(
            model_name='strain',
            name='name',
            field=models.CharField(max_length=200, db_index=True),
        ),
        migrations.AlterField(
            model_name='strain',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('pending', 'Pending'), ('approved', 'Approved'), ('archived', 'Archived')], default='draft', max_length=20, db_index=True),
        ),
        migrations.AlterField(
            model_name='location',
            name='building',
            field=models.CharField(max_length=120, db_index=True),
        ),
        migrations.AlterField(
            model_name='location',
            name='room',
            field=models.CharField(max_length=120, db_index=True),
        ),
        migrations.AlterField(
            model_name='location',
            name='freezer',
            field=models.CharField(max_length=120, db_index=True),
        ),
        migrations.AlterField(
            model_name='location',
            name='box',
            field=models.CharField(max_length=120, db_index=True),
        ),
        migrations.AlterField(
            model_name='location',
            name='position',
            field=models.CharField(max_length=120, db_index=True),
        ),
        migrations.AddIndex(
            model_name='researchdatabase',
            index=models.Index(fields=['name'], name='research_re_name_45d394_idx'),
        ),
        migrations.AddIndex(
            model_name='researchdatabase',
            index=models.Index(fields=['created_at'], name='research_re_created_24bfb0_idx'),
        ),
        migrations.AddIndex(
            model_name='databasemembership',
            index=models.Index(fields=['user', 'research_database'], name='research_da_user_id_a72632_idx'),
        ),
        migrations.AddIndex(
            model_name='databasemembership',
            index=models.Index(fields=['research_database', 'role'], name='research_da_researc_e5782c_idx'),
        ),
        migrations.AddIndex(
            model_name='organism',
            index=models.Index(fields=['research_database', 'name'], name='research_or_researc_3425b1_idx'),
        ),
        migrations.AddIndex(
            model_name='location',
            index=models.Index(fields=['research_database', 'building', 'room'], name='research_lo_researc_01f2d2_idx'),
        ),
        migrations.AddIndex(
            model_name='location',
            index=models.Index(fields=['research_database', 'freezer', 'box', 'position'], name='research_lo_researc_b695bd_idx'),
        ),
        migrations.AddIndex(
            model_name='plasmid',
            index=models.Index(fields=['research_database', 'name'], name='research_pl_researc_1a9957_idx'),
        ),
        migrations.AddIndex(
            model_name='plasmid',
            index=models.Index(fields=['research_database', 'resistance_marker'], name='research_pl_researc_9a1f8a_idx'),
        ),
        migrations.AddIndex(
            model_name='strain',
            index=models.Index(fields=['research_database', 'strain_id'], name='research_st_researc_c50bb4_idx'),
        ),
        migrations.AddIndex(
            model_name='strain',
            index=models.Index(fields=['research_database', 'status'], name='research_st_researc_46d30b_idx'),
        ),
        migrations.AddIndex(
            model_name='strain',
            index=models.Index(fields=['research_database', 'updated_at'], name='research_st_researc_21d59c_idx'),
        ),
        migrations.AddIndex(
            model_name='file',
            index=models.Index(fields=['research_database', 'uploaded_at'], name='research_fi_researc_190ceb_idx'),
        ),
        migrations.AddIndex(
            model_name='file',
            index=models.Index(fields=['strain', 'uploaded_at'], name='research_fi_strain__d7a254_idx'),
        ),
    ]
