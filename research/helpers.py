from threading import local

from django.core.exceptions import PermissionDenied
from django.forms.models import model_to_dict
from django.shortcuts import redirect
from django.urls import reverse

from .models import ActivityLog, CustomFieldDefinition, CustomFieldValue, DatabaseMembership, ResearchDatabase

SESSION_DATABASE_KEY = 'active_database_id'
LEGACY_SESSION_DATABASE_KEY = 'current_database'
_REQUEST_STATE = local()


class AuditableModelMixin:
    """Mixin that can be used by models to emit activity logs on save/delete operations."""

    def save(self, *args, **kwargs):
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return super().delete(*args, **kwargs)


def set_current_user(user):
    """Store the authenticated user in thread-local state for signal-based logging."""

    _REQUEST_STATE.user = user


def clear_current_user():
    """Clear thread-local request user state after each request."""

    if hasattr(_REQUEST_STATE, 'user'):
        delattr(_REQUEST_STATE, 'user')


def get_current_user():
    """Return the user bound to the current request thread, if available."""

    return getattr(_REQUEST_STATE, 'user', None)


def get_membership_for_database(user, research_database):
    if not user.is_authenticated or research_database is None:
        return None
    return DatabaseMembership.objects.filter(user=user, research_database=research_database).first()


def get_active_database(request):
    """Resolve and persist the authenticated user's active database.

    Returns:
        ResearchDatabase instance when available.
        HttpResponseRedirect to database creation when user has no memberships.
        None for anonymous requests.
    """

    if not request.user.is_authenticated:
        return None

    database_id = request.session.get(SESSION_DATABASE_KEY) or request.session.get(LEGACY_SESSION_DATABASE_KEY)
    if database_id:
        active_database = ResearchDatabase.objects.filter(
            id=database_id,
            memberships__user=request.user,
        ).distinct().first()
        if active_database:
            request.session[SESSION_DATABASE_KEY] = active_database.id
            if LEGACY_SESSION_DATABASE_KEY in request.session:
                request.session.pop(LEGACY_SESSION_DATABASE_KEY, None)
            return active_database

    membership = (
        DatabaseMembership.objects.select_related('research_database')
        .filter(user=request.user)
        .order_by('research_database__name', 'research_database_id')
        .first()
    )
    if membership:
        request.session[SESSION_DATABASE_KEY] = membership.research_database_id
        request.session.pop(LEGACY_SESSION_DATABASE_KEY, None)
        return membership.research_database

    return redirect(reverse('database-create'))


def get_current_database(request):
    """Backward compatible alias for older imports."""

    return get_active_database(request)


def set_current_database(request, research_database):
    request.session[SESSION_DATABASE_KEY] = research_database.id
    request.session.pop(LEGACY_SESSION_DATABASE_KEY, None)


def user_has_role(user, research_database, allowed_roles):
    membership = get_membership_for_database(user, research_database)
    if not membership:
        return False
    return membership.role in allowed_roles


def require_database_role(request, allowed_roles):
    research_database = getattr(request, 'active_database', None) or get_active_database(request)
    if hasattr(research_database, 'status_code'):
        return research_database
    if not user_has_role(request.user, research_database, allowed_roles):
        raise PermissionDenied('You do not have permission for this operation.')
    return research_database


def get_custom_field_definitions(research_database):
    if research_database is None:
        return CustomFieldDefinition.objects.none()
    return CustomFieldDefinition.objects.filter(research_database=research_database).order_by('name', 'id')


def get_custom_field_values(strain):
    if strain is None:
        return CustomFieldValue.objects.none()
    return CustomFieldValue.objects.filter(strain=strain).select_related('field_definition').order_by('field_definition__name')


def serialize_field_value(value):
    """Convert values to JSON-safe representations for diff storage."""

    if value is None:
        return None
    if hasattr(value, 'pk'):
        return str(value.pk)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value) if isinstance(value, bytes) else value


def get_change_summary(changes):
    """Build a concise human-readable sentence for a structured field diff."""

    if not changes:
        return 'No field-level changes recorded.'

    fragments = []
    for field_name, values in changes.items():
        before = values.get('before')
        after = values.get('after')
        fragments.append(f"{field_name} changed: {before} → {after}")
    return '; '.join(fragments)


def log_activity(request, instance, action, changes):
    """Create an ``ActivityLog`` entry for a model event.

    Args:
        request: Optional request object used to determine the acting user.
        instance: Model instance that changed.
        action: One of create/update/delete.
        changes: Dict of field diffs (before/after).
    """

    research_database = getattr(instance, 'research_database', None)
    if research_database is None and hasattr(instance, 'strain'):
        research_database = getattr(instance.strain, 'research_database', None)
    if research_database is None and hasattr(instance, 'field_definition'):
        definition_db = getattr(instance.field_definition, 'research_database', None)
        if definition_db is not None:
            research_database = definition_db
    if research_database is None:
        return None

    user = None
    if request is not None and getattr(request, 'user', None) and request.user.is_authenticated:
        user = request.user

    model_name = instance.__class__.__name__
    object_id = str(instance.pk)
    descriptor = str(instance)
    summary = f'{user or "System"} {action}d {model_name} {descriptor}. {get_change_summary(changes)}'

    return ActivityLog.objects.create(
        research_database=research_database,
        user=user,
        model_name=model_name,
        object_id=object_id,
        action=action,
        changes=changes,
        summary=summary,
    )


def get_instance_snapshot(instance):
    """Capture model state as a dict for change comparison in signal handlers."""

    return {
        field_name: serialize_field_value(value)
        for field_name, value in model_to_dict(instance).items()
    }
