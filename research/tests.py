from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import DatabaseMembership, Location, Organism, ResearchDatabase, Strain

User = get_user_model()


class ModelRelationshipTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='pass123')
        self.database = ResearchDatabase.objects.create(name='DB-1', created_by=self.user)

    def test_membership_links_user_and_database(self):
        membership = DatabaseMembership.objects.create(
            user=self.user,
            database=self.database,
            role=DatabaseMembership.Role.ADMIN,
        )
        self.assertEqual(membership.database, self.database)
        self.assertEqual(membership.user, self.user)

    def test_strain_belongs_to_database(self):
        organism = Organism.objects.create(database=self.database, name='E. coli')
        location = Location.objects.create(
            database=self.database,
            building='B1',
            room='R1',
            freezer='F1',
            box='BX1',
            position='P1',
        )
        strain = Strain.objects.create(
            database=self.database,
            strain_id='S-001',
            name='Example strain',
            organism=organism,
            genotype='WT',
            location=location,
            created_by=self.user,
            status=Strain.Status.DRAFT,
        )
        self.assertEqual(strain.database, self.database)


class CurrentDatabaseMiddlewareTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='bob', password='pass123')
        self.database = ResearchDatabase.objects.create(name='DB-2', created_by=self.user)

    def test_redirects_to_database_selection_when_unset(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('database-select'))

    def test_allows_when_database_in_session_and_member(self):
        DatabaseMembership.objects.create(user=self.user, database=self.database, role=DatabaseMembership.Role.VIEWER)
        self.client.force_login(self.user)
        session = self.client.session
        session['current_database_id'] = self.database.id
        session.save()

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)


class ViewPermissionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(username='admin-user', password='pass123')
        self.editor_user = User.objects.create_user(username='editor-user', password='pass123')
        self.viewer_user = User.objects.create_user(username='viewer-user', password='pass123')
        self.database = ResearchDatabase.objects.create(name='DB-3', created_by=self.admin_user)
        DatabaseMembership.objects.create(user=self.admin_user, database=self.database, role=DatabaseMembership.Role.ADMIN)
        DatabaseMembership.objects.create(user=self.editor_user, database=self.database, role=DatabaseMembership.Role.EDITOR)
        DatabaseMembership.objects.create(user=self.viewer_user, database=self.database, role=DatabaseMembership.Role.VIEWER)

    def _activate_database(self):
        session = self.client.session
        session['current_database_id'] = self.database.id
        session.save()

    def test_only_admin_can_access_membership_management_view(self):
        self.client.force_login(self.admin_user)
        self._activate_database()
        response = self.client.get(reverse('membership-list'))
        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.editor_user)
        self._activate_database()
        response = self.client.get(reverse('membership-list'))
        self.assertEqual(response.status_code, 403)

    def test_viewer_has_read_access_to_strain_list(self):
        self.client.force_login(self.viewer_user)
        self._activate_database()
        response = self.client.get(reverse('strain-list'))
        self.assertEqual(response.status_code, 200)
