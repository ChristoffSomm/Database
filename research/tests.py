import io
import json
import zipfile
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from .helpers import SESSION_DATABASE_KEY, SESSION_ORGANIZATION_KEY
from .models import (
    AuditLog,
    CustomFieldDefinition,
    CustomFieldValue,
    DatabaseMembership,
    Location,
    Organization,
    OrganizationMembership,
    Organism,
    ResearchDatabase,
    Strain,
    StrainAttachment,
)

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class DatabaseIsolationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='alice', password='pass123')
        self.db_a = ResearchDatabase.objects.create(name='DB-A', created_by=self.user)
        self.db_b = ResearchDatabase.objects.create(name='DB-B', created_by=self.user)

        DatabaseMembership.objects.update_or_create(
            user=self.user,
            research_database=self.db_a,
            defaults={'role': DatabaseMembership.Role.ADMIN},
        )
        DatabaseMembership.objects.update_or_create(
            user=self.user,
            research_database=self.db_b,
            defaults={'role': DatabaseMembership.Role.VIEWER},
        )

        organism_a = Organism.objects.create(research_database=self.db_a, name='E. coli')
        location_a = Location.objects.create(
            research_database=self.db_a,
            building='B1',
            room='R1',
            freezer='F1',
            box='BX1',
            position='P1',
        )
        self.strain_a = Strain.objects.create(
            research_database=self.db_a,
            strain_id='A-001',
            name='Strain A',
            organism=organism_a,
            genotype='WT',
            location=location_a,
            created_by=self.user,
        )

        organism_b = Organism.objects.create(research_database=self.db_b, name='B. subtilis')
        location_b = Location.objects.create(
            research_database=self.db_b,
            building='B2',
            room='R2',
            freezer='F2',
            box='BX2',
            position='P2',
        )
        self.strain_b = Strain.objects.create(
            research_database=self.db_b,
            strain_id='B-001',
            name='Strain B',
            organism=organism_b,
            genotype='MUT',
            location=location_b,
            created_by=self.user,
        )

    def test_users_only_see_data_from_active_research_database(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.db_a.id
        session.save()

        response = self.client.get(reverse('strain-list'))
        self.assertContains(response, self.strain_a.strain_id)
        self.assertNotContains(response, self.strain_b.strain_id)


@override_settings(SECURE_SSL_REDIRECT=False)
class OrganizationSnapshotTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username='snapshot-owner', password='pass123')
        self.other = User.objects.create_user(username='snapshot-other', password='pass123')
        self.organization = Organization.objects.create(name='Org Snapshot', slug='org-snapshot', created_by=self.owner)
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.organization,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.database = ResearchDatabase.objects.create(
            organization=self.organization,
            name='Snapshot DB',
            created_by=self.owner,
        )
        self.organism = Organism.objects.create(research_database=self.database, name='E. coli')
        self.location = Location.objects.create(
            research_database=self.database,
            building='B1',
            room='R1',
            freezer='F1',
            box='BX1',
            position='P1',
        )
        self.strain = Strain.objects.create(
            research_database=self.database,
            strain_id='SNAP-001',
            name='Snapshot Strain',
            organism=self.organism,
            genotype='WT',
            location=self.location,
            created_by=self.owner,
        )

    def test_export_requires_membership_and_returns_zip(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('organization-export', kwargs={'org_id': self.organization.uuid}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')

        zip_file = zipfile.ZipFile(io.BytesIO(response.content))
        payload = json.loads(zip_file.read('snapshot.json').decode('utf-8'))
        self.assertEqual(payload['version'], '1.0')
        self.assertEqual(payload['organization']['uuid'], str(self.organization.uuid))

    def test_restore_rejects_wrong_org_uuid(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('organization-export', kwargs={'org_id': self.organization.uuid}))
        zip_file = zipfile.ZipFile(io.BytesIO(response.content))
        payload = json.loads(zip_file.read('snapshot.json').decode('utf-8'))

        other_org = Organization.objects.create(name='Other', slug='other', created_by=self.owner)
        OrganizationMembership.objects.create(user=self.owner, organization=other_org, role=OrganizationMembership.Role.ADMIN)
        restore_buffer = io.BytesIO()
        with zipfile.ZipFile(restore_buffer, 'w', zipfile.ZIP_DEFLATED) as restore_zip:
            restore_zip.writestr('snapshot.json', json.dumps(payload))
        restore_buffer.seek(0)

        upload = SimpleUploadedFile('snapshot.zip', restore_buffer.getvalue(), content_type='application/zip')
        response = self.client.post(
            reverse('organization-restore', kwargs={'org_id': other_org.uuid}),
            {'snapshot_file': upload},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ResearchDatabase.objects.filter(organization=other_org).count() == 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class ActiveDatabaseMiddlewareTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='bob', password='pass123')
        self.database = ResearchDatabase.objects.create(name='DB-1', created_by=self.user)

    def test_auto_selects_first_membership_when_session_unset(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session.get(SESSION_DATABASE_KEY), self.database.id)

    def test_redirects_to_create_when_user_has_no_memberships(self):
        lone_user = User.objects.create_user(username='no-memberships', password='pass123')
        self.client.force_login(lone_user)

        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('database-create'))


@override_settings(SECURE_SSL_REDIRECT=False)
class RolePermissionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner_user = User.objects.create_user(username='owner-user', password='pass123')
        self.admin_user = User.objects.create_user(username='admin-user', password='pass123')
        self.editor_user = User.objects.create_user(username='editor-user', password='pass123')
        self.viewer_user = User.objects.create_user(username='viewer-user', password='pass123')
        self.database = ResearchDatabase.objects.create(name='DB-2', created_by=self.owner_user)

        DatabaseMembership.objects.update_or_create(
            user=self.admin_user,
            research_database=self.database,
            defaults={'role': DatabaseMembership.Role.ADMIN},
        )
        DatabaseMembership.objects.update_or_create(
            user=self.editor_user,
            research_database=self.database,
            defaults={'role': DatabaseMembership.Role.EDITOR},
        )
        DatabaseMembership.objects.update_or_create(
            user=self.viewer_user,
            research_database=self.database,
            defaults={'role': DatabaseMembership.Role.VIEWER},
        )

    def _set_active_database(self):
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()

    def test_admin_and_owner_can_manage_memberships(self):
        self.client.force_login(self.owner_user)
        self._set_active_database()
        self.assertEqual(self.client.get(reverse('membership-list')).status_code, 200)

        self.client.force_login(self.admin_user)
        self._set_active_database()
        self.assertEqual(self.client.get(reverse('membership-list')).status_code, 200)

    def test_editor_and_viewer_cannot_manage_memberships(self):
        self.client.force_login(self.editor_user)
        self._set_active_database()
        self.assertEqual(self.client.get(reverse('membership-list')).status_code, 403)

        self.client.force_login(self.viewer_user)
        self._set_active_database()
        self.assertEqual(self.client.get(reverse('membership-list')).status_code, 403)

    def test_viewer_cannot_create_strains(self):
        self.client.force_login(self.viewer_user)
        self._set_active_database()
        self.assertEqual(self.client.get(reverse('strain-create')).status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class DatabaseSelectorTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='selector-user', password='pass123')
        self.database = ResearchDatabase.objects.create(name='DB-Selector', created_by=self.user)

    def test_switch_database_sets_session_value(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('database-switch'), {'database_id': self.database.id})
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(self.client.session.get(SESSION_DATABASE_KEY), self.database.id)

    def test_switch_database_get_route_sets_session_value(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('switch_database', kwargs={'database_id': self.database.id}))
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(self.client.session.get(SESSION_DATABASE_KEY), self.database.id)


class ResearchDatabaseMembershipHelperTests(TestCase):
    def test_creator_becomes_owner_and_permission_helpers(self):
        owner = User.objects.create_user(username='db-owner', password='pass123')
        viewer = User.objects.create_user(username='db-viewer', password='pass123')
        database = ResearchDatabase.objects.create(name='AutoOwner', created_by=owner)

        DatabaseMembership.objects.create(
            user=viewer,
            research_database=database,
            role=DatabaseMembership.Role.VIEWER,
        )

        self.assertEqual(database.get_user_role(owner), DatabaseMembership.Role.OWNER)
        self.assertTrue(database.is_owner(owner))
        self.assertTrue(database.can_manage_members(owner))
        self.assertTrue(database.can_edit(owner))
        self.assertTrue(database.can_view(owner))

        self.assertEqual(database.get_user_role(viewer), DatabaseMembership.Role.VIEWER)
        self.assertFalse(database.is_owner(viewer))
        self.assertFalse(database.can_manage_members(viewer))
        self.assertFalse(database.can_edit(viewer))
        self.assertTrue(database.can_view(viewer))


@override_settings(SECURE_SSL_REDIRECT=False)
class BulkActionsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username='bulk-owner', password='pass123')
        self.editor = User.objects.create_user(username='bulk-editor', password='pass123')
        self.viewer = User.objects.create_user(username='bulk-viewer', password='pass123')
        self.database = ResearchDatabase.objects.create(name='DB-Bulk', created_by=self.owner)

        DatabaseMembership.objects.update_or_create(
            user=self.owner,
            research_database=self.database,
            defaults={'role': DatabaseMembership.Role.OWNER},
        )
        DatabaseMembership.objects.create(user=self.editor, research_database=self.database, role=DatabaseMembership.Role.EDITOR)
        DatabaseMembership.objects.create(user=self.viewer, research_database=self.database, role=DatabaseMembership.Role.VIEWER)

        self.organism = Organism.objects.create(research_database=self.database, name='E. coli')
        self.location = Location.objects.create(
            research_database=self.database,
            building='BLD',
            room='R1',
            freezer='F1',
            box='B1',
            position='P1',
        )
        self.strain_one = Strain.objects.create(
            research_database=self.database,
            strain_id='S-001',
            name='One',
            organism=self.organism,
            genotype='WT',
            location=self.location,
            created_by=self.owner,
        )
        self.strain_two = Strain.objects.create(
            research_database=self.database,
            strain_id='S-002',
            name='Two',
            organism=self.organism,
            genotype='WT',
            location=self.location,
            created_by=self.owner,
        )

    def _set_active_database(self):
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()

    def test_bulk_edit_updates_selected_fields(self):
        self.client.force_login(self.editor)
        self._set_active_database()

        response = self.client.post(
            reverse('strain-bulk-edit'),
            {
                'bulk_action': 'edit',
                'apply_bulk_edit': '1',
                'strain_ids': [self.strain_one.id, self.strain_two.id],
                'genotype': 'Updated',
                'comments': 'Bulk comment',
            },
        )

        self.assertRedirects(response, reverse('strain-list'))
        self.strain_one.refresh_from_db()
        self.strain_two.refresh_from_db()
        self.assertEqual(self.strain_one.genotype, 'Updated')
        self.assertEqual(self.strain_two.comments, 'Bulk comment')

    def test_bulk_archive_marks_is_archived(self):
        self.client.force_login(self.editor)
        self._set_active_database()
        response = self.client.post(
            reverse('strain-bulk-edit'),
            {'bulk_action': 'archive', 'strain_ids': [self.strain_one.id]},
        )
        self.assertRedirects(response, reverse('strain-list'))
        self.strain_one.refresh_from_db()
        self.assertTrue(self.strain_one.is_archived)

    def test_bulk_delete_forbidden_for_editor(self):
        self.client.force_login(self.editor)
        self._set_active_database()
        response = self.client.post(
            reverse('strain-bulk-edit'),
            {'bulk_action': 'delete', 'strain_ids': [self.strain_one.id]},
        )
        self.assertEqual(response.status_code, 400)

    def test_bulk_delete_allowed_for_owner(self):
        self.client.force_login(self.owner)
        self._set_active_database()
        response = self.client.post(
            reverse('strain-bulk-edit'),
            {'bulk_action': 'delete', 'strain_ids': [self.strain_one.id]},
        )
        self.assertRedirects(response, reverse('strain-list'))
        self.strain_one.refresh_from_db()
        self.assertFalse(self.strain_one.is_active)

@override_settings(SECURE_SSL_REDIRECT=False)
class CSVImportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username='csv-owner', password='pass123')
        self.viewer = User.objects.create_user(username='csv-viewer', password='pass123')
        self.database = ResearchDatabase.objects.create(name='CSV-DB', created_by=self.owner)

        DatabaseMembership.objects.create(user=self.owner, research_database=self.database, role=DatabaseMembership.Role.EDITOR)
        DatabaseMembership.objects.create(user=self.viewer, research_database=self.database, role=DatabaseMembership.Role.VIEWER)

        self.organism = Organism.objects.create(research_database=self.database, name='E. coli')
        self.location = Location.objects.create(
            research_database=self.database,
            building='B1',
            room='R1',
            freezer='F1',
            box='BX1',
            position='P1',
        )

    def _set_active_database(self):
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()


    def test_unknown_organism_is_auto_created_during_import(self):
        self.client.force_login(self.owner)
        self._set_active_database()

        csv_content = "strain_id,organism,genotype,location\nS-200,New Organism,WT,Box 1 A1\n"
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile('auto-create.csv', csv_content.encode('utf-8'), content_type='text/csv')

        upload_response = self.client.post(reverse('csv_upload'), {'action': 'upload', 'file': upload})
        self.assertEqual(upload_response.status_code, 302)

        mapping_response = self.client.post(
            reverse('csv_upload'),
            {
                'action': 'mapping',
                'map_strain_id': 'strain_id',
                'map_organism': 'organism',
                'map_genotype': 'genotype',
                'map_location': 'location',
            },
        )
        self.assertEqual(mapping_response.status_code, 302)

        confirm_response = self.client.post(reverse('csv_upload'), {'action': 'confirm_import'})
        self.assertRedirects(confirm_response, reverse('strain-list'))

        organism = Organism.objects.get(research_database=self.database, name='New Organism')
        strain = Strain.objects.get(research_database=self.database, strain_id='S-200')
        self.assertEqual(strain.organism, organism.name)
        self.assertTrue(
            AuditLog.objects.filter(
                database=self.database,
                action='AUTO_CREATE_ORGANISM',
                object_type='Organism',
                object_id=organism.id,
                metadata__organism='New Organism',
            ).exists()
        )

    def test_viewer_cannot_access_csv_import(self):
        self.client.force_login(self.viewer)
        self._set_active_database()
        response = self.client.get(reverse('csv_upload'))
        self.assertEqual(response.status_code, 403)

    def test_editor_can_import_csv_and_duplicates_are_skipped(self):
        self.client.force_login(self.owner)
        self._set_active_database()

        csv_content = "strain_id,organism,genotype,location,comments\nS-100,E. coli,WT,B1 / R1 / F1 / BX1 / P1,First\nS-100,E. coli,WT,B1 / R1 / F1 / BX1 / P1,Duplicate\n"
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile('strains.csv', csv_content.encode('utf-8'), content_type='text/csv')

        response = self.client.post(reverse('csv_upload'), {'action': 'upload', 'file': upload})
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse('csv_upload'),
            {
                'action': 'mapping',
                'map_strain_id': 'strain_id',
                'map_organism': 'organism',
                'map_genotype': 'genotype',
                'map_location': 'location',
                'map_comments': 'comments',
            },
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(reverse('csv_upload'), {'action': 'confirm_import'})
        self.assertRedirects(response, reverse('strain-list'))

        self.assertEqual(Strain.objects.filter(research_database=self.database, strain_id='S-100').count(), 1)
        self.assertTrue(
            self.database.auditlog_set.filter(
                action='csv_import',
                metadata__rows_created=1,
                metadata__rows_skipped=1,
                metadata__filename='strains.csv',
            ).exists()
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class StrainAttachmentViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username='attach-owner', password='pass123')
        self.admin = User.objects.create_user(username='attach-admin', password='pass123')
        self.editor = User.objects.create_user(username='attach-editor', password='pass123')
        self.viewer = User.objects.create_user(username='attach-viewer', password='pass123')
        self.database = ResearchDatabase.objects.create(name='ATT-DB', created_by=self.owner)

        DatabaseMembership.objects.update_or_create(
            user=self.owner,
            research_database=self.database,
            defaults={'role': DatabaseMembership.Role.OWNER},
        )
        DatabaseMembership.objects.create(user=self.admin, research_database=self.database, role=DatabaseMembership.Role.ADMIN)
        DatabaseMembership.objects.create(user=self.editor, research_database=self.database, role=DatabaseMembership.Role.EDITOR)
        DatabaseMembership.objects.create(user=self.viewer, research_database=self.database, role=DatabaseMembership.Role.VIEWER)

        organism = Organism.objects.create(research_database=self.database, name='E. coli')
        location = Location.objects.create(
            research_database=self.database,
            building='B1',
            room='R1',
            freezer='F1',
            box='BX1',
            position='P1',
        )
        self.strain = Strain.objects.create(
            research_database=self.database,
            strain_id='ATT-001',
            name='Attachment Test',
            organism=organism,
            genotype='WT',
            location=location,
            created_by=self.owner,
        )

    def _set_active_database(self):
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()

    def test_editor_can_upload_multiple_attachments(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.editor)
        self._set_active_database()
        response = self.client.post(
            reverse('strain-attachment-upload', kwargs={'pk': self.strain.pk}),
            {
                'files': [
                    SimpleUploadedFile('protocol.txt', b'abc', content_type='text/plain'),
                    SimpleUploadedFile('gel.png', b'png-bytes', content_type='image/png'),
                ]
            },
        )

        self.assertRedirects(response, reverse('strain-detail', kwargs={'pk': self.strain.pk}))
        self.assertEqual(StrainAttachment.objects.filter(strain=self.strain).count(), 2)
        self.assertTrue(
            AuditLog.objects.filter(action='upload', object_type='StrainAttachment', metadata__strain_id='ATT-001').exists()
        )

    def test_viewer_cannot_upload_attachments(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.viewer)
        self._set_active_database()
        response = self.client.post(
            reverse('strain-attachment-upload', kwargs={'pk': self.strain.pk}),
            {'files': [SimpleUploadedFile('notes.txt', b'abc', content_type='text/plain')]},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_delete_but_editor_cannot(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        attachment = StrainAttachment.objects.create(
            strain=self.strain,
            uploaded_by=self.owner,
            file=SimpleUploadedFile('to-delete.txt', b'data', content_type='text/plain'),
        )

        self.client.force_login(self.editor)
        self._set_active_database()
        denied = self.client.post(
            reverse('strain-attachment-delete', kwargs={'pk': self.strain.pk, 'attachment_pk': attachment.pk})
        )
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(self.admin)
        self._set_active_database()
        allowed = self.client.post(
            reverse('strain-attachment-delete', kwargs={'pk': self.strain.pk, 'attachment_pk': attachment.pk})
        )
        self.assertRedirects(allowed, reverse('strain-detail', kwargs={'pk': self.strain.pk}))
        self.assertFalse(StrainAttachment.objects.filter(pk=attachment.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='delete', object_type='StrainAttachment').exists())

    def test_download_requires_matching_database(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        attachment = StrainAttachment.objects.create(
            strain=self.strain,
            uploaded_by=self.owner,
            file=SimpleUploadedFile('readme.txt', b'hello', content_type='text/plain'),
        )

        self.client.force_login(self.viewer)
        self._set_active_database()
        response = self.client.get(
            reverse('strain-attachment-download', kwargs={'pk': self.strain.pk, 'attachment_pk': attachment.pk})
        )
        self.assertEqual(response.status_code, 200)

        other_db = ResearchDatabase.objects.create(name='Other DB', created_by=self.owner)
        DatabaseMembership.objects.create(user=self.viewer, research_database=other_db, role=DatabaseMembership.Role.VIEWER)
        session = self.client.session
        session[SESSION_DATABASE_KEY] = other_db.id
        session.save()

        denied = self.client.get(
            reverse('strain-attachment-download', kwargs={'pk': self.strain.pk, 'attachment_pk': attachment.pk})
        )
        self.assertEqual(denied.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class DashboardAnalyticsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='dashboard-user', password='pass123')
        self.database = ResearchDatabase.objects.create(name='Analytics DB', created_by=self.user)
        DatabaseMembership.objects.update_or_create(
            user=self.user,
            research_database=self.database,
            defaults={'role': DatabaseMembership.Role.VIEWER},
        )

        self.organism_a = Organism.objects.create(research_database=self.database, name='E. coli')
        self.organism_b = Organism.objects.create(research_database=self.database, name='S. cerevisiae')

        self.location_a = Location.objects.create(
            research_database=self.database,
            building='A',
            room='R1',
            freezer='F1',
            box='B1',
            position='P1',
        )
        self.location_b = Location.objects.create(
            research_database=self.database,
            building='B',
            room='R2',
            freezer='F2',
            box='B2',
            position='P2',
        )

        self.choice_field = CustomFieldDefinition.objects.create(
            research_database=self.database,
            name='Resistance',
            field_type=CustomFieldDefinition.FieldType.CHOICE,
            choices='Amp,Kan',
            created_by=self.user,
        )

    def _set_active_database(self):
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()

    def test_dashboard_metrics_and_chart_payloads_render(self):
        strain_one = Strain.objects.create(
            research_database=self.database,
            strain_id='D-001',
            name='Dash One',
            organism=self.organism_a,
            genotype='WT',
            location=self.location_a,
            status=Strain.Status.ARCHIVED,
            is_archived=True,
            created_by=self.user,
        )
        strain_two = Strain.objects.create(
            research_database=self.database,
            strain_id='D-002',
            name='Dash Two',
            organism=self.organism_a,
            genotype='WT',
            location=self.location_b,
            created_by=self.user,
        )
        strain_three = Strain.objects.create(
            research_database=self.database,
            strain_id='D-003',
            name='Dash Three',
            organism=self.organism_b,
            genotype='MUT',
            location=self.location_b,
            created_by=self.user,
        )
        Strain.objects.filter(id=strain_three.id).update(created_at=timezone.now() - timedelta(days=90))

        CustomFieldValue.objects.create(strain=strain_one, field_definition=self.choice_field, value_choice='Amp')
        CustomFieldValue.objects.create(strain=strain_two, field_definition=self.choice_field, value_choice='Amp')

        self.client.force_login(self.user)
        self._set_active_database()

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_strains'], 3)
        self.assertEqual(response.context['total_archived'], 1)
        self.assertEqual(response.context['strains_added_last_30_days'], 2)
        self.assertTrue(response.context['has_strains'])
        self.assertContains(response, 'organism-chart-data')
        self.assertContains(response, 'location-chart-data')
        self.assertContains(response, 'monthly-chart-data')
        self.assertContains(response, 'Resistance')

    def test_dashboard_empty_state_when_no_strains(self):
        self.client.force_login(self.user)
        self._set_active_database()

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_strains'], 0)
        self.assertFalse(response.context['has_strains'])
        self.assertContains(response, 'No strain data yet')


@override_settings(SECURE_SSL_REDIRECT=False)
class StrainArchiveWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username='arc-owner', password='pass123')
        self.admin = User.objects.create_user(username='arc-admin', password='pass123')
        self.editor = User.objects.create_user(username='arc-editor', password='pass123')
        self.database = ResearchDatabase.objects.create(name='DB-Archive', created_by=self.owner)

        DatabaseMembership.objects.create(user=self.owner, research_database=self.database, role=DatabaseMembership.Role.OWNER)
        DatabaseMembership.objects.create(user=self.admin, research_database=self.database, role=DatabaseMembership.Role.ADMIN)
        DatabaseMembership.objects.create(user=self.editor, research_database=self.database, role=DatabaseMembership.Role.EDITOR)

        self.organism = Organism.objects.create(research_database=self.database, name='S. cerevisiae')
        self.location = Location.objects.create(
            research_database=self.database,
            building='ARC',
            room='R1',
            freezer='F1',
            box='B1',
            position='P1',
        )
        self.strain = Strain.all_objects.create(
            research_database=self.database,
            strain_id='ARC-001',
            name='Archive Target',
            organism=self.organism,
            genotype='WT',
            location=self.location,
            created_by=self.owner,
        )

    def _set_active_database(self):
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()

    def test_editor_can_archive_and_restore_strain(self):
        self.client.force_login(self.editor)
        self._set_active_database()

        archive_response = self.client.post(reverse('strain-archive', kwargs={'pk': self.strain.pk}))
        self.assertEqual(archive_response.status_code, 302)
        self.strain.refresh_from_db()
        self.assertTrue(self.strain.is_archived)
        self.assertEqual(self.strain.archived_by, self.editor)

        restore_response = self.client.post(reverse('strain-restore', kwargs={'pk': self.strain.pk}))
        self.assertEqual(restore_response.status_code, 302)
        self.strain.refresh_from_db()
        self.assertFalse(self.strain.is_archived)
        self.assertIsNone(self.strain.archived_by)

        self.assertTrue(AuditLog.objects.filter(action='archive', object_id=self.strain.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='restore', object_id=self.strain.pk).exists())

    def test_admin_can_hard_delete_strain(self):
        self.client.force_login(self.admin)
        self._set_active_database()

        response = self.client.post(reverse('strain-hard-delete', kwargs={'pk': self.strain.pk}))
        self.assertRedirects(response, reverse('strain-list'))
        self.assertFalse(Strain.all_objects.filter(pk=self.strain.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='delete').exists())

    def test_editor_cannot_hard_delete_strain(self):
        self.client.force_login(self.editor)
        self._set_active_database()

        response = self.client.post(reverse('strain-hard-delete', kwargs={'pk': self.strain.pk}))
        self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class OrganizationAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='org-user', password='pass123', is_staff=True)
        self.other = User.objects.create_user(username='org-other', password='pass123')

        self.org_a = Organization.objects.create(name='Org A', slug='org-a', created_by=self.user)
        self.org_b = Organization.objects.create(name='Org B', slug='org-b', created_by=self.user)
        OrganizationMembership.objects.update_or_create(user=self.user, organization=self.org_a, defaults={'role': OrganizationMembership.Role.ADMIN})
        OrganizationMembership.objects.update_or_create(user=self.user, organization=self.org_b, defaults={'role': OrganizationMembership.Role.ADMIN})

        self.db_a = ResearchDatabase.objects.create(name='OrgA-DB', organization=self.org_a, created_by=self.user)
        self.db_b = ResearchDatabase.objects.create(name='OrgB-DB', organization=self.org_b, created_by=self.user)
        DatabaseMembership.objects.update_or_create(user=self.user, research_database=self.db_a, defaults={'role': DatabaseMembership.Role.ADMIN})
        DatabaseMembership.objects.update_or_create(user=self.user, research_database=self.db_b, defaults={'role': DatabaseMembership.Role.ADMIN})

    def test_database_select_only_shows_active_organization_databases(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[SESSION_ORGANIZATION_KEY] = self.org_a.id
        session.save()

        response = self.client.get(reverse('database-select'))
        self.assertContains(response, 'OrgA-DB')
        self.assertNotContains(response, 'OrgB-DB')

    def test_switch_organization_resets_active_database(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[SESSION_ORGANIZATION_KEY] = self.org_a.id
        session[SESSION_DATABASE_KEY] = self.db_a.id
        session.save()

        response = self.client.post(reverse('organization-switch-id', kwargs={'organization_id': self.org_b.id}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get(SESSION_ORGANIZATION_KEY), self.org_b.id)
        self.assertIsNone(self.client.session.get(SESSION_DATABASE_KEY))
