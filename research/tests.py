from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .helpers import SESSION_DATABASE_KEY
from .models import DatabaseMembership, Location, Organism, ResearchDatabase, Strain

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

        DatabaseMembership.objects.create(user=self.owner, research_database=self.database, role=DatabaseMembership.Role.OWNER)
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
