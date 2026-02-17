from django.http import HttpResponseForbidden

from .helpers import get_active_database


class DatabasePermissionMixin:
    required_permission = 'view'

    def get_active_database(self):
        return getattr(self.request, 'active_database', None) or get_active_database(self.request)

    def get_current_database(self):
        return self.get_active_database()

    def has_database_permission(self, database, user):
        permission_map = {
            'view': database.can_view,
            'edit': database.can_edit,
            'manage_members': database.can_manage_members,
            'owner': database.is_owner,
            'admin': lambda user: database.get_user_role(user) == 'admin',
        }
        checker = permission_map.get(self.required_permission)
        if checker is None:
            return False
        return checker(user)

    def dispatch(self, request, *args, **kwargs):
        database = self.get_active_database()
        if hasattr(database, 'status_code'):
            return database
        if database is None:
            return HttpResponseForbidden('No active database selected.')
        if not self.has_database_permission(database, request.user):
            return HttpResponseForbidden('Insufficient permissions for this database.')
        return super().dispatch(request, *args, **kwargs)
