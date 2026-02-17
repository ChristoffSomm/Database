from django.contrib.auth import get_user_model
import os
import uuid
from django.utils.text import slugify

from django.db import models
from django.urls import reverse
from django.utils import timezone

User = get_user_model()


class UserProfile(models.Model):
    class ThemePreference(models.TextChoices):
        LIGHT = 'light', 'Light'
        DARK = 'dark', 'Dark'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    theme_preference = models.CharField(
        max_length=10,
        choices=ThemePreference.choices,
        default=ThemePreference.LIGHT,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f'{self.user.username} profile'


class Organization(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_organizations')

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['slug']), models.Index(fields=['created_at'])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_user_role(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return None
        membership = self.memberships.filter(user=user).only('role').first()
        return membership.role if membership else None

    def can_manage_members(self, user):
        return self.get_user_role(user) == OrganizationMembership.Role.ADMIN

    def can_add_databases(self, user):
        return self.get_user_role(user) == OrganizationMembership.Role.ADMIN


class OrganizationMembership(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        MEMBER = 'member', 'Member'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='organization_memberships')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER, db_index=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'organization')
        ordering = ['organization__name', 'user__username']
        indexes = [models.Index(fields=['organization', 'role']), models.Index(fields=['user', 'organization'])]

    def __str__(self):
        return f'{self.user} @ {self.organization} ({self.role})'


class ResearchDatabase(models.Model):
    organization = models.ForeignKey('Organization', on_delete=models.CASCADE, related_name='databases')
    name = models.CharField(max_length=200, db_index=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_research_databases')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['name']), models.Index(fields=['created_at'])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.organization_id is None and self.created_by_id:
            organization, _created = Organization.objects.get_or_create(
                slug=f'user-{self.created_by_id}',
                defaults={'name': f'{self.created_by.username} Organization', 'created_by': self.created_by},
            )
            self.organization = organization
        super().save(*args, **kwargs)

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


class ActiveStrainManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_archived=False)


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
    selective_marker = models.CharField(max_length=255, blank=True)
    comments = models.TextField(blank=True)
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='strains')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_strains')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='archived_strains')
    plasmids = models.ManyToManyField(Plasmid, through='StrainPlasmid', related_name='strains', blank=True)

    objects = ActiveStrainManager()
    all_objects = models.Manager()

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

    def archive(self, user):
        self.is_archived = True
        self.archived_at = timezone.now()
        self.archived_by = user
        self.save(update_fields=['is_archived', 'archived_at', 'archived_by', 'updated_at'])

    def restore(self):
        self.is_archived = False
        self.archived_at = None
        self.archived_by = None
        self.save(update_fields=['is_archived', 'archived_at', 'archived_by', 'updated_at'])

    def save(self, *args, **kwargs):
        from .helpers import get_current_user
        from .versioning import serialize_strain_snapshot

        skip_version = kwargs.pop('skip_version', False)
        changed_by = kwargs.pop('changed_by', None)
        is_update = bool(self.pk) and not self._state.adding
        if is_update and not skip_version:
            previous_state = Strain.all_objects.filter(pk=self.pk).first()
            if previous_state is not None:
                StrainVersion.objects.create(
                    strain=previous_state,
                    changed_by=changed_by or get_current_user(),
                    snapshot=serialize_strain_snapshot(previous_state),
                )
        return super().save(*args, **kwargs)


class StrainVersion(models.Model):
    strain = models.ForeignKey(Strain, on_delete=models.CASCADE, related_name='versions')
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    snapshot = models.JSONField()

    class Meta:
        ordering = ['-changed_at']
        indexes = [models.Index(fields=['strain', 'changed_at'])]

    def __str__(self):
        return f'StrainVersion<{self.strain_id}> @ {self.changed_at.isoformat()}'


class CustomFieldDefinition(models.Model):
    class FieldType(models.TextChoices):
        TEXT = 'text', 'Text'
        LONG_TEXT = 'long_text', 'Long text'
        INTEGER = 'integer', 'Integer'
        DECIMAL = 'decimal', 'Decimal'
        DATE = 'date', 'Date'
        BOOLEAN = 'boolean', 'Boolean'
        SINGLE_SELECT = 'single_select', 'Single select'
        MULTI_SELECT = 'multi_select', 'Multi select'
        FOREIGN_KEY = 'foreign_key', 'Foreign key'
        FILE = 'file', 'File'
        URL = 'url', 'URL'
        EMAIL = 'email', 'Email'

    NUMBER = 'integer'
    CHOICE = 'single_select'

    class RelatedModel(models.TextChoices):
        ORGANISM = 'organism', 'Organism'
        PLASMID = 'plasmid', 'Plasmid'
        LOCATION = 'location', 'Location'

    name = models.CharField(max_length=200)
    label = models.CharField(max_length=200, blank=True, default='')
    key = models.SlugField(max_length=100, blank=True, default='')
    field_type = models.CharField(max_length=20, choices=FieldType.choices)
    choices = models.JSONField(default=list, blank=True)
    default_value = models.JSONField(default=dict, blank=True)
    help_text = models.TextField(blank=True)
    validation_rules = models.JSONField(default=dict, blank=True)
    is_unique = models.BooleanField(default=False)
    conditional_logic = models.JSONField(default=dict, blank=True)
    order = models.PositiveIntegerField(default=0, db_index=True)
    visible_to_roles = models.JSONField(default=list, blank=True)
    editable_to_roles = models.JSONField(default=list, blank=True)
    related_model = models.CharField(max_length=30, choices=RelatedModel.choices, blank=True)
    group = models.ForeignKey('CustomFieldGroup', on_delete=models.SET_NULL, null=True, blank=True, related_name='fields')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='custom_field_definitions', null=True, blank=True)
    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='custom_field_definitions')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_custom_field_definitions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']
        unique_together = (('research_database', 'name'), ('research_database', 'key'))
        indexes = [
            models.Index(fields=['research_database', 'field_type']),
            models.Index(fields=['research_database', 'name']),
            models.Index(fields=['research_database', 'order']),
            models.Index(fields=['organization', 'research_database']),
        ]

    def __str__(self):
        return f'{self.label or self.name} ({self.get_field_type_display()})'

    def save(self, *args, **kwargs):
        if not self.label:
            self.label = self.name
        if not self.key:
            self.key = slugify(self.name)
        if not self.organization_id and self.research_database_id:
            self.organization_id = self.research_database.organization_id
        super().save(*args, **kwargs)

    def parsed_choices(self):
        if self.field_type not in {self.FieldType.SINGLE_SELECT, self.FieldType.MULTI_SELECT}:
            return []
        if isinstance(self.choices, str):
            return [choice.strip() for choice in self.choices.split(',') if choice.strip()]
        return [str(choice).strip() for choice in self.choices if str(choice).strip()]


class CustomFieldGroup(models.Model):
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0, db_index=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='custom_field_groups', null=True, blank=True)
    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='custom_field_groups')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_custom_field_groups')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'name']
        unique_together = ('research_database', 'name')

    def __str__(self):
        return self.name


class CustomFieldVisibilityRule(models.Model):
    field_definition = models.ForeignKey(CustomFieldDefinition, on_delete=models.CASCADE, related_name='visibility_rules')
    role = models.CharField(max_length=20, choices=DatabaseMembership.Role.choices)
    can_view = models.BooleanField(default=True)
    can_edit = models.BooleanField(default=True)

    class Meta:
        unique_together = ('field_definition', 'role')

    def __str__(self):
        return f'{self.field_definition.key}:{self.role}'


class CustomFieldValue(models.Model):
    strain = models.ForeignKey(Strain, on_delete=models.CASCADE, related_name='custom_field_values')
    field_definition = models.ForeignKey(CustomFieldDefinition, on_delete=models.CASCADE, related_name='values')
    value_text = models.TextField(null=True, blank=True)
    value_long_text = models.TextField(null=True, blank=True)
    value_number = models.FloatField(null=True, blank=True)
    value_integer = models.IntegerField(null=True, blank=True)
    value_decimal = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    value_date = models.DateField(null=True, blank=True)
    value_boolean = models.BooleanField(null=True, blank=True)
    value_choice = models.CharField(max_length=255, null=True, blank=True)
    value_single_select = models.CharField(max_length=255, null=True, blank=True)
    value_multi_select = models.JSONField(default=list, blank=True)
    value_fk_content_type = models.ForeignKey('contenttypes.ContentType', on_delete=models.SET_NULL, null=True, blank=True)
    value_fk_object_id = models.PositiveIntegerField(null=True, blank=True)
    value_file = models.FileField(upload_to='custom_field_files/', null=True, blank=True)
    value_url = models.URLField(max_length=500, null=True, blank=True)
    value_email = models.EmailField(max_length=254, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['strain', 'field_definition'], name='unique_strain_custom_field_value')]
        indexes = [
            models.Index(fields=['field_definition', 'value_single_select']),
            models.Index(fields=['field_definition', 'value_integer']),
            models.Index(fields=['field_definition', 'value_date']),
            models.Index(fields=['strain', 'field_definition']),
            models.Index(fields=['value_fk_content_type', 'value_fk_object_id']),
        ]

    def __str__(self):
        return f'{self.strain} | {self.field_definition.name}'

    @property
    def display_value(self):
        field_type = self.field_definition.field_type
        if field_type == CustomFieldDefinition.FieldType.TEXT:
            return self.value_text
        if field_type == CustomFieldDefinition.FieldType.LONG_TEXT:
            return self.value_long_text
        if field_type == CustomFieldDefinition.FieldType.INTEGER:
            return self.value_integer
        if field_type == CustomFieldDefinition.FieldType.DECIMAL:
            return self.value_decimal
        if field_type == CustomFieldDefinition.FieldType.DATE:
            return self.value_date
        if field_type == CustomFieldDefinition.FieldType.BOOLEAN:
            if self.value_boolean is None:
                return ''
            return 'Yes' if self.value_boolean else 'No'
        if field_type == CustomFieldDefinition.FieldType.SINGLE_SELECT:
            return self.value_single_select
        if field_type == CustomFieldDefinition.FieldType.MULTI_SELECT:
            return ', '.join(self.value_multi_select or [])
        if field_type == CustomFieldDefinition.FieldType.FOREIGN_KEY and self.value_fk_content_type_id and self.value_fk_object_id:
            model_class = self.value_fk_content_type.model_class()
            if model_class:
                return model_class.objects.filter(pk=self.value_fk_object_id).first()
        if field_type == CustomFieldDefinition.FieldType.FILE:
            return self.value_file
        if field_type == CustomFieldDefinition.FieldType.URL:
            return self.value_url
        if field_type == CustomFieldDefinition.FieldType.EMAIL:
            return self.value_email
        return ''


class StrainPlasmid(models.Model):
    strain = models.ForeignKey(Strain, on_delete=models.CASCADE)
    plasmid = models.ForeignKey(Plasmid, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('strain', 'plasmid')

    def __str__(self):
        return f'{self.strain.strain_id} -> {self.plasmid.name}'


class SavedView(models.Model):
    research_database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='saved_views')
    name = models.CharField(max_length=255)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_views')
    filter_definition = models.JSONField()
    is_shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', '-created_at']
        unique_together = ('research_database', 'name', 'created_by')
        indexes = [
            models.Index(fields=['research_database', 'is_shared']),
            models.Index(fields=['research_database', 'created_by']),
            models.Index(fields=['research_database', 'created_at']),
        ]

    def __str__(self):
        visibility = 'Shared' if self.is_shared else 'Private'
        return f'{self.name} ({visibility})'


class StrainAttachment(models.Model):
    strain = models.ForeignKey(Strain, on_delete=models.CASCADE, related_name='attachments')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='strain_attachments')
    file = models.FileField(upload_to='strain_attachments/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['strain', 'uploaded_at']),
            models.Index(fields=['uploaded_at']),
        ]

    def __str__(self):
        return f'{self.strain.strain_id}: {self.file_name}'

    @property
    def extension(self):
        _root, extension = os.path.splitext(self.file_name or '')
        return extension.lower().lstrip('.')

    @property
    def is_image(self):
        return self.extension in {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'}

    def save(self, *args, **kwargs):
        if self.file:
            self.file_name = os.path.basename(self.file.name)
            self.file_size = self.file.size or 0
        super().save(*args, **kwargs)


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
    database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='audit_logs', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=120)
    object_type = models.CharField(max_length=120, default='')
    object_id = models.IntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['database', 'timestamp']),
            models.Index(fields=['database', 'action']),
            models.Index(fields=['database', 'object_type', 'object_id']),
        ]

    def __str__(self):
        return f'{self.timestamp.isoformat()} | {self.user} | {self.action} | {self.object_type}:{self.object_id}'
