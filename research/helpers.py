from django.core.exceptions import PermissionDenied

from .models import DatabaseMembership, ResearchDatabase

SESSION_DATABASE_KEY = 'current_database'


def get_membership_for_database(user, research_database):
    if not user.is_authenticated or research_database is None:
        return None
    return DatabaseMembership.objects.filter(user=user, research_database=research_database).first()


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


def set_current_database(request, research_database):
    request.session[SESSION_DATABASE_KEY] = research_database.id


def user_has_role(user, research_database, allowed_roles):
    membership = get_membership_for_database(user, research_database)
    if not membership:
        return False
    return membership.role in allowed_roles


def require_database_role(request, allowed_roles):
    research_database = getattr(request, 'current_database', None) or get_current_database(request)
    if not user_has_role(request.user, research_database, allowed_roles):
        raise PermissionDenied('You do not have permission for this operation.')
    return research_database
