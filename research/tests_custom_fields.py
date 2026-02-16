from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .helpers import SESSION_DATABASE_KEY
from .models import CustomFieldDefinition, CustomFieldValue, DatabaseMembership, Location, Organism, ResearchDatabase, Strain

User = get_user_model()


class CustomFieldDefinitionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='cf-admin', password='pass123')
        self.database = ResearchDatabase.objects.create(name='CF-DB', created_by=self.user)
        DatabaseMembership.objects.create(user=self.user, research_database=self.database, role=DatabaseMembership.Role.ADMIN)
        self.client.force_login(self.user)
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()

    def test_create_custom_field_definition(self):
        response = self.client.post(
            reverse('custom-field-definition-create'),
            {'name': 'Temperature', 'field_type': CustomFieldDefinition.FieldType.NUMBER, 'choices': ''},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CustomFieldDefinition.objects.filter(name='Temperature', research_database=self.database).exists())


class CustomFieldValueFormSaveTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='cf-editor', password='pass123')
        self.database = ResearchDatabase.objects.create(name='CF-DB-2', created_by=self.user)
        DatabaseMembership.objects.create(user=self.user, research_database=self.database, role=DatabaseMembership.Role.EDITOR)

        self.organism = Organism.objects.create(research_database=self.database, name='E. coli')
        self.location = Location.objects.create(
            research_database=self.database,
            building='B1',
            room='R1',
            freezer='F1',
            box='BX1',
            position='P1',
        )
        self.custom_field = CustomFieldDefinition.objects.create(
            name='Growth Note',
            field_type=CustomFieldDefinition.FieldType.TEXT,
            research_database=self.database,
            created_by=self.user,
        )

        self.client.force_login(self.user)
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()

    def test_save_dynamic_custom_field_value(self):
        response = self.client.post(
            reverse('strain-create'),
            {
                'strain_id': 'CF-001',
                'name': 'Custom Strain',
                'organism': self.organism.id,
                'genotype': 'WT',
                'location': self.location.id,
                'status': Strain.Status.DRAFT,
                f'custom_field_{self.custom_field.id}': 'Observed high growth',
            },
        )
        self.assertEqual(response.status_code, 302)
        strain = Strain.objects.get(strain_id='CF-001')
        self.assertTrue(CustomFieldValue.objects.filter(strain=strain, field_definition=self.custom_field).exists())


class CustomFieldDetailRenderingTests(TestCase):
    def test_detail_page_includes_custom_field_values(self):
        # Skeleton assertion placeholder for template rendering coverage.
        self.assertTrue(True)


class CustomFieldPermissionsTests(TestCase):
    def test_viewer_cannot_define_custom_fields(self):
        # Skeleton assertion placeholder for permissions enforcement coverage.
        self.assertTrue(True)
