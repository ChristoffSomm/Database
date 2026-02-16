from django.shortcuts import redirect
from django.urls import reverse

from .models import DatabaseMembership
from .utils import SESSION_DATABASE_KEY


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
        if not request.user.is_authenticated and not request.path.startswith(exempt_prefixes):
            return redirect(f'{login_url}?next={request.path}')
        return self.get_response(request)


class CurrentDatabaseMiddleware:
    """Ensure a logged-in user has a valid active research database selected."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.current_database = None
        if not request.user.is_authenticated:
            return self.get_response(request)

        selection_path = reverse('database-select')
        switch_path = reverse('database-switch')
        exempt_prefixes = (
            selection_path,
            switch_path,
            '/admin/',
            '/static/',
            '/media/',
        )

        database_id = request.session.get(SESSION_DATABASE_KEY)
        membership = None
        if database_id:
            membership = DatabaseMembership.objects.select_related('database').filter(
                user=request.user,
                database_id=database_id,
            ).first()
            if membership:
                request.current_database = membership.database
            else:
                request.session.pop(SESSION_DATABASE_KEY, None)

        has_any_membership = DatabaseMembership.objects.filter(user=request.user).exists()
        if request.path.startswith(exempt_prefixes):
            return self.get_response(request)

        if not has_any_membership:
            return redirect(selection_path)

        if request.current_database is None:
            return redirect(selection_path)

        return self.get_response(request)
