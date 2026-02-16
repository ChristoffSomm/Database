from django.contrib import admin

from .models import AuditLog, File, Location, Organism, Plasmid, Strain, StrainPlasmid


class StrainPlasmidInline(admin.TabularInline):
    model = StrainPlasmid
    extra = 1


@admin.register(Strain)
class StrainAdmin(admin.ModelAdmin):
    list_display = ('strain_id', 'name', 'organism', 'location', 'status', 'created_by', 'updated_at')
    search_fields = ('strain_id', 'name', 'genotype')
    list_filter = ('status', 'organism')
    inlines = [StrainPlasmidInline]


@admin.register(Organism)
class OrganismAdmin(admin.ModelAdmin):
    search_fields = ('name',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('building', 'room', 'freezer', 'box', 'position')
    search_fields = ('building', 'room', 'freezer', 'box', 'position')


@admin.register(Plasmid)
class PlasmidAdmin(admin.ModelAdmin):
    list_display = ('name', 'resistance_marker')
    search_fields = ('name', 'resistance_marker')


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ('strain', 'file', 'uploaded_by', 'uploaded_at')
    search_fields = ('strain__strain_id', 'file')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'record_type', 'record_id')
    search_fields = ('action', 'record_type', 'record_id', 'user__username')
    readonly_fields = ('timestamp',)
