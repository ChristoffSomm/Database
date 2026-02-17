from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .dynamic_forms import evaluate_condition_logic
from .forms import StrainForm
from .helpers import SESSION_DATABASE_KEY
from .models import (
    CustomFieldDefinition,
    CustomFieldGroup,
    CustomFieldValue,
    DatabaseMembership,
    Location,
    Organism,
    Organization,
    OrganizationMembership,
    Plasmid,
    ResearchDatabase,
    Strain,
)

User = get_user_model()


class CustomFieldSchemaBuilderTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.owner = User.objects.create_user(username='owner', password='pass123')
        self.viewer = User.objects.create_user(username='viewer', password='pass123')
        self.organization = Organization.objects.create(name='Org', slug='org', created_by=self.owner)
        OrganizationMembership.objects.create(user=self.owner, organization=self.organization, role=OrganizationMembership.Role.ADMIN)
        self.database = ResearchDatabase.objects.create(name='CF-DB', created_by=self.owner, organization=self.organization)
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
        self.plasmid = Plasmid.objects.create(research_database=self.database, name='pAMP', resistance_marker='AMP')

        self.group = CustomFieldGroup.objects.create(
            name='Culture',
            order=1,
            organization=self.organization,
            research_database=self.database,
            created_by=self.owner,
        )

    def _request_for(self, user):
        request = self.factory.get('/')
        request.user = user
        request.session = {SESSION_DATABASE_KEY: self.database.id}
        request.active_database = self.database
        return request

    def test_dynamic_form_builder_and_value_save(self):
        marker = CustomFieldDefinition.objects.create(
            name='Selective Marker',
            label='Selective Marker',
            key='selective_marker_custom',
            field_type=CustomFieldDefinition.FieldType.SINGLE_SELECT,
            choices=['AMP', 'KAN'],
            validation_rules={'required': True},
            group=self.group,
            order=1,
            organization=self.organization,
            research_database=self.database,
            created_by=self.owner,
        )
        count = CustomFieldDefinition.objects.create(
            name='Colony Count',
            label='Colony Count',
            key='colony_count',
            field_type=CustomFieldDefinition.FieldType.INTEGER,
            conditional_logic={'operator': 'AND', 'conditions': [{'field': 'custom_selective_marker_custom', 'operator': 'equals', 'value': 'AMP'}]},
            is_unique=True,
            group=self.group,
            order=2,
            organization=self.organization,
            research_database=self.database,
            created_by=self.owner,
        )

        request = self._request_for(self.owner)
        form = StrainForm(
            data={
                'strain_id': 'S-001',
                'name': 'Dynamic strain',
                'organism': self.organism.id,
                'genotype': 'WT',
                'location': self.location.id,
                'status': Strain.Status.DRAFT,
                'custom_selective_marker_custom': 'AMP',
                'custom_colony_count': 12,
            },
            request=request,
        )
        self.assertTrue(form.is_valid(), form.errors)
        strain = form.save()
        self.assertEqual(CustomFieldValue.objects.get(strain=strain, field_definition=marker).value_single_select, 'AMP')
        self.assertEqual(CustomFieldValue.objects.get(strain=strain, field_definition=count).value_integer, 12)

    def test_conditional_logic_engine(self):
        logic = {
            'operator': 'AND',
            'conditions': [{'field': 'selective_marker', 'operator': 'equals', 'value': 'AMP'}],
        }
        self.assertTrue(evaluate_condition_logic(logic, {'selective_marker': 'AMP'}))
        self.assertFalse(evaluate_condition_logic(logic, {'selective_marker': 'KAN'}))

    def test_visibility_and_permission(self):
        hidden = CustomFieldDefinition.objects.create(
            name='Editor Only',
            label='Editor Only',
            key='editor_only',
            field_type=CustomFieldDefinition.FieldType.TEXT,
            visible_to_roles=[DatabaseMembership.Role.EDITOR],
            editable_to_roles=[DatabaseMembership.Role.EDITOR],
            group=self.group,
            order=3,
            organization=self.organization,
            research_database=self.database,
            created_by=self.owner,
        )
        viewer_form = StrainForm(request=self._request_for(self.viewer))
        self.assertNotIn('custom_editor_only', viewer_form.fields)

        owner_form = StrainForm(request=self._request_for(self.owner))
        self.assertIn('custom_editor_only', owner_form.fields)

        self.client.force_login(self.viewer)
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()
        response = self.client.get(reverse('custom-field-definition-create'))
        self.assertEqual(response.status_code, 403)

    def test_foreign_key_custom_field(self):
        fk_field = CustomFieldDefinition.objects.create(
            name='Linked Plasmid',
            label='Linked Plasmid',
            key='linked_plasmid',
            field_type=CustomFieldDefinition.FieldType.FOREIGN_KEY,
            related_model=CustomFieldDefinition.RelatedModel.PLASMID,
            group=self.group,
            order=4,
            organization=self.organization,
            research_database=self.database,
            created_by=self.owner,
        )
        form = StrainForm(
            data={
                'strain_id': 'S-002',
                'name': 'FK strain',
                'organism': self.organism.id,
                'genotype': 'WT',
                'location': self.location.id,
                'status': Strain.Status.DRAFT,
                'custom_linked_plasmid': self.plasmid.id,
            },
            request=self._request_for(self.owner),
        )
        self.assertTrue(form.is_valid(), form.errors)
        strain = form.save()
        value = CustomFieldValue.objects.get(strain=strain, field_definition=fk_field)
        self.assertEqual(value.value_fk_object_id, self.plasmid.id)
