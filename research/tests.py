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
