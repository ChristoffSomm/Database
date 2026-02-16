from django.contrib import admin

from .models import (
    AuditLog,
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
        if obj is not None and hasattr(obj, 'database'):
            return obj.database

        db_id = request.session.get('current_database_id')
        if db_id:
            return ResearchDatabase.objects.filter(id=db_id).first()
        return None

    def _role_for_user(self, request, database):
        if request.user.is_superuser:
            return DatabaseMembership.Role.ADMIN
        if database is None:
            return None
        membership = DatabaseMembership.objects.filter(user=request.user, database=database).first()
        return membership.role if membership else None

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser or not hasattr(self.model, 'database'):
            return queryset

        db_id = request.session.get('current_database_id')
        if not db_id:
            return queryset.none()

        return queryset.filter(database_id=db_id)

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
    list_display = ('name', 'created_by', 'created_at')
    search_fields = ('name', 'description', 'created_by__username')


@admin.register(DatabaseMembership)
class DatabaseMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'database', 'role', 'created_at')
    list_filter = ('role', 'database')
    search_fields = ('user__username', 'database__name')


@admin.register(Strain)
class StrainAdmin(DatabaseScopedAdmin):
    list_display = ('strain_id', 'name', 'database', 'organism', 'location', 'status', 'created_by', 'updated_at')
    search_fields = ('strain_id', 'name', 'genotype')
    list_filter = ('status', 'organism', 'database')
    inlines = [StrainPlasmidInline]


@admin.register(Organism)
class OrganismAdmin(DatabaseScopedAdmin):
    list_display = ('name', 'database')
    search_fields = ('name',)


@admin.register(Location)
class LocationAdmin(DatabaseScopedAdmin):
    list_display = ('database', 'building', 'room', 'freezer', 'box', 'position')
    search_fields = ('building', 'room', 'freezer', 'box', 'position')


@admin.register(Plasmid)
class PlasmidAdmin(DatabaseScopedAdmin):
    list_display = ('name', 'database', 'resistance_marker')
    search_fields = ('name', 'resistance_marker')


@admin.register(File)
class FileAdmin(DatabaseScopedAdmin):
    list_display = ('strain', 'database', 'file', 'uploaded_by', 'uploaded_at')
    search_fields = ('strain__strain_id', 'file')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'record_type', 'record_id')
    search_fields = ('action', 'record_type', 'record_id', 'user__username')
    readonly_fields = ('timestamp',)
