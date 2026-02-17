from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .helpers import SESSION_DATABASE_KEY
from .models import ActivityLog, AuditLog, DatabaseMembership, Location, Organism, ResearchDatabase, Strain

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class ActivityLoggingTests(TestCase):
    """Skeleton test coverage for signal-driven activity logging."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='auditor', password='pass123')
        self.viewer = User.objects.create_user(username='viewer', password='pass123')
        self.database = ResearchDatabase.objects.create(name='Audit DB', created_by=self.user)
        self.other_database = ResearchDatabase.objects.create(name='Other DB', created_by=self.user)

        DatabaseMembership.objects.create(user=self.user, research_database=self.database, role=DatabaseMembership.Role.ADMIN)
        DatabaseMembership.objects.create(user=self.viewer, research_database=self.database, role=DatabaseMembership.Role.VIEWER)

        self.organism = Organism.objects.create(research_database=self.database, name='E. coli')
        self.location = Location.objects.create(
            research_database=self.database,
            building='A',
            room='101',
            freezer='FZ1',
            box='BOX1',
            position='P1',
        )

    def _set_active_database(self):
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()

    def test_activity_logging_on_create(self):
        strain = Strain.objects.create(
            research_database=self.database,
            strain_id='S-001',
            name='CreateTest',
            organism=self.organism,
            genotype='WT',
            location=self.location,
            created_by=self.user,
        )
        self.assertTrue(ActivityLog.objects.filter(model_name='Strain', object_id=str(strain.pk), action='create').exists())

    def test_activity_logging_on_update_records_diff(self):
        strain = Strain.objects.create(
            research_database=self.database,
            strain_id='S-002',
            name='Before',
            organism=self.organism,
            genotype='WT',
            location=self.location,
            created_by=self.user,
        )
        strain.name = 'After'
        strain.save(update_fields=['name'])

        update_log = ActivityLog.objects.filter(model_name='Strain', object_id=str(strain.pk), action='update').latest('timestamp')
        self.assertIn('name', update_log.changes)
        self.assertEqual(update_log.changes['name']['before'], 'Before')
        self.assertEqual(update_log.changes['name']['after'], 'After')

    def test_activity_logging_on_delete(self):
        strain = Strain.objects.create(
            research_database=self.database,
            strain_id='S-003',
            name='DeleteMe',
            organism=self.organism,
            genotype='WT',
            location=self.location,
            created_by=self.user,
        )
        strain_pk = strain.pk
        strain.delete()
        self.assertTrue(ActivityLog.objects.filter(model_name='Strain', object_id=str(strain_pk), action='delete').exists())

    def test_activity_feed_filters_by_research_database(self):
        self.client.force_login(self.user)
        self._set_active_database()
        other_org = Organism.objects.create(research_database=self.other_database, name='B. subtilis')
        other_loc = Location.objects.create(
            research_database=self.other_database,
            building='B',
            room='202',
            freezer='FZ2',
            box='BOX2',
            position='P2',
        )
        Strain.objects.create(
            research_database=self.other_database,
            strain_id='S-999',
            name='OtherDB',
            organism=other_org,
            genotype='mut',
            location=other_loc,
            created_by=self.user,
        )

        response = self.client.get(reverse('activity-feed'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(log.research_database_id == self.database.id for log in response.context['activity_logs']))


    def test_activity_feed_uses_audit_logs_for_active_database(self):
        self.client.force_login(self.user)
        self._set_active_database()

        AuditLog.objects.create(
            database=self.database,
            user=self.user,
            action='archive',
            object_type='Strain',
            object_id=1,
            metadata={'strain_id': 'S-001'},
        )
        AuditLog.objects.create(
            database=self.other_database,
            user=self.user,
            action='archive',
            object_type='Strain',
            object_id=2,
            metadata={'strain_id': 'S-999'},
        )

        response = self.client.get(reverse('activity-feed'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['activity_logs']), 1)
        self.assertEqual(response.context['activity_logs'][0].database_id, self.database.id)

    def test_activity_feed_action_filter(self):
        self.client.force_login(self.user)
        self._set_active_database()

        AuditLog.objects.create(
            database=self.database,
            user=self.user,
            action='archive',
            object_type='Strain',
            object_id=1,
            metadata={'strain_id': 'S-001'},
        )
        AuditLog.objects.create(
            database=self.database,
            user=self.user,
            action='upload',
            object_type='StrainAttachment',
            object_id=3,
            metadata={'filename': 'map.png'},
        )

        response = self.client.get(reverse('activity-feed'), {'action': 'upload'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['activity_logs']), 1)
        self.assertEqual(response.context['activity_logs'][0].action, 'upload')

    def test_activity_feed_permissions_enforced(self):
        outsider = User.objects.create_user(username='outsider', password='pass123')
        self.client.force_login(outsider)
        session = self.client.session
        session[SESSION_DATABASE_KEY] = self.database.id
        session.save()

        response = self.client.get(reverse('activity-feed'))
        self.assertEqual(response.status_code, 302)
