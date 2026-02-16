from django.apps import AppConfig


class ResearchConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'research'

    def ready(self):
        """Register signal handlers for automatic activity logging."""

        from . import signals  # noqa: F401
