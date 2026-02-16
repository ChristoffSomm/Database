from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class ResearchDatabase(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_research_databases')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class DatabaseMembership(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        EDITOR = 'editor', 'Editor'
        VIEWER = 'viewer', 'Viewer'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='database_memberships')
    database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'database')
        ordering = ['database__name', 'user__username']

    def __str__(self):
        return f'{self.user} @ {self.database} ({self.role})'


class Organism(models.Model):
    database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='organisms')
    name = models.CharField(max_length=200)

    class Meta:
        unique_together = ('database', 'name')

    def __str__(self):
        return self.name


class Location(models.Model):
    database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='locations')
    building = models.CharField(max_length=120)
    room = models.CharField(max_length=120)
    freezer = models.CharField(max_length=120)
    box = models.CharField(max_length=120)
    position = models.CharField(max_length=120)

    class Meta:
        unique_together = ('database', 'building', 'room', 'freezer', 'box', 'position')

    def __str__(self):
        return f'{self.building} / {self.room} / {self.freezer} / {self.box} / {self.position}'


class Plasmid(models.Model):
    database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='plasmids')
    name = models.CharField(max_length=150)
    resistance_marker = models.CharField(max_length=150)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ('database', 'name')

    def __str__(self):
        return self.name


class Strain(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        ARCHIVED = 'archived', 'Archived'

    database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='strains')
    strain_id = models.CharField(max_length=60)
    name = models.CharField(max_length=200)
    organism = models.ForeignKey(Organism, on_delete=models.PROTECT, related_name='strains')
    genotype = models.TextField()
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='strains')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_strains')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    plasmids = models.ManyToManyField(Plasmid, through='StrainPlasmid', related_name='strains', blank=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ('database', 'strain_id')

    def __str__(self):
        return f'{self.strain_id} - {self.name}'


class StrainPlasmid(models.Model):
    strain = models.ForeignKey(Strain, on_delete=models.CASCADE)
    plasmid = models.ForeignKey(Plasmid, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('strain', 'plasmid')

    def __str__(self):
        return f'{self.strain.strain_id} -> {self.plasmid.name}'


class File(models.Model):
    database = models.ForeignKey(ResearchDatabase, on_delete=models.CASCADE, related_name='files')
    strain = models.ForeignKey(Strain, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to='strain_files/%Y/%m/%d')
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='uploaded_files')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.strain.strain_id}: {self.file.name}'


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
