from django.shortcuts import redirect
from django.urls import reverse


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
