from django.shortcuts import redirect
from django.urls import reverse

from .helpers import (
    SESSION_DATABASE_KEY,
    SESSION_ORGANIZATION_KEY,
    clear_current_user,
    get_active_database,
    get_active_organization,
    set_current_user,
)
from .models import DatabaseMembership, OrganizationMembership


class LoginRequiredMiddleware:
    """Require authentication for all non-exempt routes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        login_url = reverse('login')
        exempt_prefixes = (
            login_url,
            reverse('logout'),
            '/admin/',
            '/static/',
            '/media/',
        )
        set_current_user(request.user if request.user.is_authenticated else None)
        try:
            if not request.user.is_authenticated and not request.path.startswith(exempt_prefixes):
                return redirect(f'{login_url}?next={request.path}')
            return self.get_response(request)
        finally:
            clear_current_user()


class ActiveOrganizationMiddleware:
    """Attach the active organization to requests and keep session selection valid."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.active_organization = None

        if not request.user.is_authenticated:
            return self.get_response(request)

        exempt_prefixes = (
            reverse('organization-create'),
            reverse('organization-list'),
            reverse('organization-switch'),
            '/admin/',
            '/static/',
            '/media/',
        )
        if request.path.startswith(exempt_prefixes):
            return self.get_response(request)

        active_organization = get_active_organization(request)
        if active_organization and not OrganizationMembership.objects.filter(
            user=request.user,
            organization=active_organization,
        ).exists():
            request.session.pop(SESSION_ORGANIZATION_KEY, None)
            active_organization = get_active_organization(request)

        request.active_organization = active_organization
        return self.get_response(request)


class ActiveDatabaseMiddleware:
    """Attach the active database to requests and keep session selection valid."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.active_database = None
        request.current_database = None

        if not request.user.is_authenticated:
            return self.get_response(request)

        exempt_prefixes = (
            reverse('database-create'),
            reverse('database-select'),
            reverse('database-switch'),
            '/switch-database/',
            '/admin/',
            '/static/',
            '/media/',
        )
        if request.path.startswith(exempt_prefixes):
            return self.get_response(request)

        active_organization = getattr(request, 'active_organization', None) or get_active_organization(request)
        request.active_organization = active_organization

        active_database = get_active_database(request)
        if hasattr(active_database, 'status_code'):
            return active_database

        if active_database and not DatabaseMembership.objects.filter(
            user=request.user,
            research_database=active_database,
            research_database__organization=active_organization,
        ).exists():
            request.session.pop(SESSION_DATABASE_KEY, None)
            active_database = get_active_database(request)
            if hasattr(active_database, 'status_code'):
                return active_database

        request.active_database = active_database
        request.current_database = active_database
        return self.get_response(request)


CurrentDatabaseMiddleware = ActiveDatabaseMiddleware
