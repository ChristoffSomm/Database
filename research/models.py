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


class DatabaseMembership(models.Model):
    class Role(models.TextChoices):
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
