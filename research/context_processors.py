from .helpers import get_active_database
from .models import DatabaseMembership


def current_database_context(request):
    memberships = []
    active_database = None
    if request.user.is_authenticated:
        memberships = DatabaseMembership.objects.select_related('research_database').filter(user=request.user).order_by(
            'research_database__name'
        )
        active_database = getattr(request, 'active_database', None) or get_active_database(request)
        if hasattr(active_database, 'status_code'):
            active_database = None
    return {
        'available_memberships': memberships,
        'active_database': active_database,
        'current_database': active_database,
    }
