from django.contrib import admin

admin.site.site_header = "HelixMapr Administration"
admin.site.site_title = "HelixMapr Admin"
admin.site.index_title = "HelixMapr Control Panel"

from .helpers import SESSION_DATABASE_KEY
from .models import (
    ActivityLog,
    AuditLog,
    CustomFieldDefinition,
    CustomFieldGroup,
    CustomFieldValue,
    CustomFieldVisibilityRule,
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
    list_display = ('label', 'key', 'field_type', 'group', 'order', 'organization', 'research_database', 'created_by', 'created_at')
    list_filter = ('organization', 'research_database', 'field_type', 'created_at')
    ordering = ('order', 'id')
    search_fields = ('name', 'label', 'key', 'research_database__name', 'created_by__username')


@admin.register(CustomFieldValue)
class CustomFieldValueAdmin(DatabaseScopedAdmin):
    list_display = ('strain', 'field_definition', 'value_text', 'value_long_text', 'value_integer', 'value_decimal', 'value_date', 'value_boolean', 'value_single_select')
    list_filter = ('field_definition__research_database', 'field_definition__organization', 'field_definition__field_type')
    search_fields = ('strain__strain_id', 'field_definition__name', 'value_text', 'value_long_text', 'value_single_select', 'value_email', 'value_url')




@admin.register(CustomFieldGroup)
class CustomFieldGroupAdmin(DatabaseScopedAdmin):
    list_display = ('name', 'order', 'organization', 'research_database', 'created_by', 'created_at')
    list_filter = ('organization', 'research_database')
    ordering = ('order', 'name')


@admin.register(CustomFieldVisibilityRule)
class CustomFieldVisibilityRuleAdmin(DatabaseScopedAdmin):
    list_display = ('field_definition', 'role', 'can_view', 'can_edit')
    list_filter = ('role', 'field_definition__research_database')


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


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'research_database', 'user', 'model_name', 'action', 'object_id')
    list_filter = ('model_name', 'action', 'user', 'research_database', 'timestamp')
    search_fields = ('summary', 'model_name')
    readonly_fields = ('timestamp', 'research_database', 'user', 'model_name', 'object_id', 'action', 'changes', 'summary')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'database', 'user', 'action', 'object_type', 'object_id')
    search_fields = ('action', 'object_type', 'object_id', 'user__username')
    readonly_fields = ('timestamp',)
