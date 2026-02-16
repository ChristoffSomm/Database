from .models import DatabaseMembership
from .utils import get_current_database


def current_database_context(request):
    memberships = []
    current_database = None
    if request.user.is_authenticated:
        memberships = DatabaseMembership.objects.select_related('database').filter(user=request.user).order_by('database__name')
        current_database = getattr(request, 'current_database', None) or get_current_database(request)
    return {
        'available_memberships': memberships,
        'current_database': current_database,
    }
