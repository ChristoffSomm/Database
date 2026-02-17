from .helpers import get_active_database, get_active_organization
from .models import DatabaseMembership, OrganizationMembership


def current_database_context(request):
    memberships = []
    organization_memberships = []
    active_database = None
    active_organization = None
    if request.user.is_authenticated:
        organization_memberships = OrganizationMembership.objects.select_related('organization').filter(
            user=request.user
        ).order_by('organization__name')
        active_organization = getattr(request, 'active_organization', None) or get_active_organization(request)

        memberships = DatabaseMembership.objects.select_related('research_database', 'research_database__organization').filter(
            user=request.user
        )
        if active_organization:
            memberships = memberships.filter(research_database__organization=active_organization)
        memberships = memberships.order_by('research_database__name')

        active_database = getattr(request, 'active_database', None) or get_active_database(request)
        if hasattr(active_database, 'status_code'):
            active_database = None

    return {
        'available_memberships': memberships,
        'available_organization_memberships': organization_memberships,
        'active_database': active_database,
        'current_database': active_database,
        'active_organization': active_organization,
    }

