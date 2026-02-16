from django.contrib import admin

from .helpers import SESSION_DATABASE_KEY
from .models import (
    AuditLog,
    CustomFieldDefinition,
    CustomFieldValue,
    DatabaseMembership,
    File,
    Location,
    Organism,
    Plasmid,
    ResearchDatabase,
    Strain,
    StrainPlasmid,
)


class DatabaseScopedAdmin(admin.ModelAdmin):
    """Restrict edit/delete rights by membership role inside the selected database."""

    def _database_for_obj(self, request, obj=None):
        if obj is not None and hasattr(obj, 'research_database'):
            return obj.research_database

        if obj is not None and hasattr(obj, 'strain'):
            return obj.strain.research_database

        db_id = request.session.get(SESSION_DATABASE_KEY)
        if db_id:
            return ResearchDatabase.objects.filter(id=db_id).first()
        return None

    def _role_for_user(self, request, database):
        if request.user.is_superuser:
            return DatabaseMembership.Role.ADMIN
        if database is None:
            return None
        membership = DatabaseMembership.objects.filter(user=request.user, research_database=database).first()
        return membership.role if membership else None

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset

        db_id = request.session.get(SESSION_DATABASE_KEY)
        if not db_id:
            return queryset.none()

        if hasattr(self.model, 'research_database'):
            return queryset.filter(research_database_id=db_id)

        if self.model is CustomFieldValue:
            return queryset.filter(strain__research_database_id=db_id)

        return queryset

    def has_add_permission(self, request):
        database = self._database_for_obj(request)
        role = self._role_for_user(request, database)
        return role in {DatabaseMembership.Role.ADMIN, DatabaseMembership.Role.EDITOR}

    def has_change_permission(self, request, obj=None):
        database = self._database_for_obj(request, obj)
        role = self._role_for_user(request, database)
        return role in {DatabaseMembership.Role.ADMIN, DatabaseMembership.Role.EDITOR}

    def has_delete_permission(self, request, obj=None):
        database = self._database_for_obj(request, obj)
        role = self._role_for_user(request, database)
        return role == DatabaseMembership.Role.ADMIN


class StrainPlasmidInline(admin.TabularInline):
    model = StrainPlasmid
    extra = 1


@admin.register(ResearchDatabase)
class ResearchDatabaseAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'created_by', 'created_at')
    search_fields = ('name', 'description', 'created_by__username', 'created_by__email')
    list_filter = ('created_at',)


@admin.register(DatabaseMembership)
class DatabaseMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'research_database', 'role', 'created_at')
    list_filter = ('role', 'research_database', 'created_at')
    search_fields = ('user__username', 'user__email', 'research_database__name')


@admin.register(Strain)
class StrainAdmin(DatabaseScopedAdmin):
    list_display = ('strain_id', 'name', 'research_database', 'organism', 'location', 'status', 'created_by', 'updated_at')
    search_fields = ('strain_id', 'name', 'genotype')
    list_filter = ('status', 'organism', 'research_database')
    inlines = [StrainPlasmidInline]


@admin.register(CustomFieldDefinition)
class CustomFieldDefinitionAdmin(DatabaseScopedAdmin):
    list_display = ('name', 'field_type', 'research_database', 'created_by', 'created_at')
    list_filter = ('field_type', 'research_database', 'created_at')
    search_fields = ('name', 'choices', 'research_database__name', 'created_by__username')


@admin.register(CustomFieldValue)
class CustomFieldValueAdmin(DatabaseScopedAdmin):
    list_display = ('strain', 'field_definition', 'value_text', 'value_number', 'value_date', 'value_boolean', 'value_choice')
    list_filter = ('field_definition__field_type', 'field_definition__research_database')
    search_fields = ('strain__strain_id', 'field_definition__name', 'value_text', 'value_choice')


@admin.register(Organism)
class OrganismAdmin(DatabaseScopedAdmin):
    list_display = ('name', 'research_database')
    search_fields = ('name',)
    list_filter = ('research_database',)


@admin.register(Location)
class LocationAdmin(DatabaseScopedAdmin):
    list_display = ('research_database', 'building', 'room', 'freezer', 'box', 'position')
    search_fields = ('building', 'room', 'freezer', 'box', 'position')
    list_filter = ('research_database', 'building', 'room')


@admin.register(Plasmid)
class PlasmidAdmin(DatabaseScopedAdmin):
    list_display = ('name', 'research_database', 'resistance_marker')
    search_fields = ('name', 'resistance_marker')
    list_filter = ('research_database', 'resistance_marker')


@admin.register(File)
class FileAdmin(DatabaseScopedAdmin):
    list_display = ('strain', 'research_database', 'file', 'uploaded_by', 'uploaded_at')
    search_fields = ('strain__strain_id', 'file')
    list_filter = ('research_database', 'uploaded_at')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'record_type', 'record_id')
    search_fields = ('action', 'record_type', 'record_id', 'user__username')
    readonly_fields = ('timestamp',)
