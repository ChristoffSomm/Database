from django.contrib.auth import get_user_model
from django.db import models
from django.urls import reverse

User = get_user_model()


class ResearchDatabase(models.Model):
    name = models.CharField(max_length=200, db_index=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_research_databases')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['name']), models.Index(fields=['created_at'])]

    def __str__(self):
        return self.name

    def get_user_role(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return None
        membership = self.memberships.filter(user=user).only('role').first()
        return membership.role if membership else None

    def is_owner(self, user):
        return self.get_user_role(user) == DatabaseMembership.Role.OWNER

    def can_edit(self, user):
        return self.get_user_role(user) in {
            DatabaseMembership.Role.OWNER,
            DatabaseMembership.Role.ADMIN,
            DatabaseMembership.Role.EDITOR,
        }

    def can_view(self, user):
        return self.get_user_role(user) in {
            DatabaseMembership.Role.OWNER,
            DatabaseMembership.Role.ADMIN,
            DatabaseMembership.Role.EDITOR,
            DatabaseMembership.Role.VIEWER,
        }

    def can_manage_members(self, user):
        return self.get_user_role(user) in {
            DatabaseMembership.Role.OWNER,
            DatabaseMembership.Role.ADMIN,
        }


class DatabaseMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        ADMIN = 'admin', 'Admin'
        EDITOR = 'editor', 'Editor'
        VIEWER = 'viewer', 'Viewer'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='database_memberships')
    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'research_database')
        ordering = ['research_database__name', 'user__username']
        indexes = [models.Index(fields=['user', 'research_database']), models.Index(fields=['research_database', 'role'])]

    def __str__(self):
        return f'{self.user} @ {self.research_database} ({self.role})'


class Organism(models.Model):
    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='organisms')
    name = models.CharField(max_length=200, db_index=True)

    class Meta:
        unique_together = ('research_database', 'name')
        indexes = [models.Index(fields=['research_database', 'name'])]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('organism-detail', kwargs={'pk': self.pk})


class Location(models.Model):
    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='locations')
    building = models.CharField(max_length=120, db_index=True)
    room = models.CharField(max_length=120, db_index=True)
    freezer = models.CharField(max_length=120, db_index=True)
    box = models.CharField(max_length=120, db_index=True)
    position = models.CharField(max_length=120, db_index=True)

    class Meta:
        unique_together = ('research_database', 'building', 'room', 'freezer', 'box', 'position')
        indexes = [
            models.Index(fields=['research_database', 'building', 'room']),
            models.Index(fields=['research_database', 'freezer', 'box', 'position']),
        ]

    def __str__(self):
        return f'{self.building} / {self.room} / {self.freezer} / {self.box} / {self.position}'

    def get_absolute_url(self):
        return reverse('location-detail', kwargs={'pk': self.pk})


class Plasmid(models.Model):
    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='plasmids')
    name = models.CharField(max_length=150, db_index=True)
    resistance_marker = models.CharField(max_length=150, db_index=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ('research_database', 'name')
        indexes = [models.Index(fields=['research_database', 'name']), models.Index(fields=['research_database', 'resistance_marker'])]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('plasmid-detail', kwargs={'pk': self.pk})


class Strain(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        ARCHIVED = 'archived', 'Archived'

    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='strains')
    strain_id = models.CharField(max_length=60, db_index=True)
    name = models.CharField(max_length=200, db_index=True)
    organism = models.ForeignKey(Organism, on_delete=models.PROTECT, related_name='strains')
    genotype = models.TextField()
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='strains')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_strains')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)
    plasmids = models.ManyToManyField(Plasmid, through='StrainPlasmid', related_name='strains', blank=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ('research_database', 'strain_id')
        indexes = [
            models.Index(fields=['research_database', 'strain_id']),
            models.Index(fields=['research_database', 'name']),
            models.Index(fields=['research_database', 'status']),
            models.Index(fields=['research_database', 'updated_at']),
        ]

    def __str__(self):
        return f'{self.strain_id} - {self.name}'

    def get_absolute_url(self):
        return reverse('strain-detail', kwargs={'pk': self.pk})


class CustomFieldDefinition(models.Model):
    class FieldType(models.TextChoices):
        TEXT = 'text', 'Text'
        NUMBER = 'number', 'Number'
        DATE = 'date', 'Date'
        BOOLEAN = 'boolean', 'Boolean'
        CHOICE = 'choice', 'Choice'

    name = models.CharField(max_length=200)
    field_type = models.CharField(max_length=20, choices=FieldType.choices)
    choices = models.TextField(blank=True)
    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='custom_field_definitions')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_custom_field_definitions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ('research_database', 'name')
        indexes = [models.Index(fields=['research_database', 'field_type']), models.Index(fields=['research_database', 'name'])]

    def __str__(self):
        return f'{self.name} ({self.get_field_type_display()})'

    def parsed_choices(self):
        if self.field_type != self.FieldType.CHOICE:
            return []
        return [choice.strip() for choice in self.choices.split(',') if choice.strip()]


class CustomFieldValue(models.Model):
    strain = models.ForeignKey(Strain, on_delete=models.CASCADE, related_name='custom_field_values')
    field_definition = models.ForeignKey(CustomFieldDefinition, on_delete=models.CASCADE, related_name='values')
    value_text = models.TextField(null=True, blank=True)
    value_number = models.FloatField(null=True, blank=True)
    value_date = models.DateField(null=True, blank=True)
    value_boolean = models.BooleanField(null=True, blank=True)
    value_choice = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['strain', 'field_definition'], name='unique_strain_custom_field_value')]
        indexes = [
            models.Index(fields=['field_definition', 'value_choice']),
            models.Index(fields=['field_definition', 'value_number']),
            models.Index(fields=['field_definition', 'value_date']),
            models.Index(fields=['strain', 'field_definition']),
        ]

    def __str__(self):
        return f'{self.strain} | {self.field_definition.name}'

    @property
    def display_value(self):
        field_type = self.field_definition.field_type
        if field_type == CustomFieldDefinition.FieldType.TEXT:
            return self.value_text
        if field_type == CustomFieldDefinition.FieldType.NUMBER:
            return self.value_number
        if field_type == CustomFieldDefinition.FieldType.DATE:
            return self.value_date
        if field_type == CustomFieldDefinition.FieldType.BOOLEAN:
            if self.value_boolean is None:
                return ''
            return 'Yes' if self.value_boolean else 'No'
        if field_type == CustomFieldDefinition.FieldType.CHOICE:
            return self.value_choice
        return ''


class StrainPlasmid(models.Model):
    strain = models.ForeignKey(Strain, on_delete=models.CASCADE)
    plasmid = models.ForeignKey(Plasmid, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('strain', 'plasmid')

    def __str__(self):
        return f'{self.strain.strain_id} -> {self.plasmid.name}'


class File(models.Model):
    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='files')
    strain = models.ForeignKey(Strain, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to='strain_files/%Y/%m/%d')
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='uploaded_files')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['research_database', 'file']),
            models.Index(fields=['research_database', 'uploaded_at']),
            models.Index(fields=['strain', 'uploaded_at']),
        ]

    def __str__(self):
        return f'{self.strain.strain_id}: {self.file.name}'

    @property
    def filename(self):
        return self.file.name.rsplit('/', 1)[-1]

    def get_absolute_url(self):
        return reverse('file-detail', kwargs={'pk': self.pk})


class ActivityLog(models.Model):
    """Immutable audit record for data mutations in core research models."""

    class Action(models.TextChoices):
        CREATE = 'create', 'Create'
        UPDATE = 'update', 'Update'
        DELETE = 'delete', 'Delete'

    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='activity_logs')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_logs')
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    model_name = models.CharField(max_length=120, db_index=True)
    object_id = models.CharField(max_length=120, db_index=True)
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)
    changes = models.JSONField(default=dict, blank=True)
    summary = models.TextField()

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['research_database', 'timestamp']),
            models.Index(fields=['research_database', 'model_name', 'action']),
        ]

    def __str__(self):
        return f'{self.timestamp.isoformat()} | {self.model_name}({self.object_id}) | {self.action}'


class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=120)
    record_type = models.CharField(max_length=120)
    record_id = models.CharField(max_length=120)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.timestamp.isoformat()} | {self.user} | {self.action}'
