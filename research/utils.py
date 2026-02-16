from django.core.exceptions import PermissionDenied

from .models import DatabaseMembership, ResearchDatabase

SESSION_DATABASE_KEY = 'current_database_id'


def get_membership_for_database(user, database):
    if not user.is_authenticated or database is None:
        return None
    return DatabaseMembership.objects.filter(user=user, database=database).first()


def get_current_database(request):
    if not request.user.is_authenticated:
        return None

    database_id = request.session.get(SESSION_DATABASE_KEY)
    if not database_id:
        return None

    return ResearchDatabase.objects.filter(
        id=database_id,
        memberships__user=request.user,
    ).distinct().first()


def set_current_database(request, database):
    request.session[SESSION_DATABASE_KEY] = database.id


def user_has_role(user, database, allowed_roles):
    membership = get_membership_for_database(user, database)
    if not membership:
        return False
    return membership.role in allowed_roles


def require_database_role(request, allowed_roles):
    database = getattr(request, 'current_database', None) or get_current_database(request)
    if not user_has_role(request.user, database, allowed_roles):
        raise PermissionDenied('You do not have permission for this operation.')
    return database
