from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .helpers import get_current_user, get_instance_snapshot, log_activity
from .models import (
    CustomFieldDefinition,
    CustomFieldValue,
    DatabaseMembership,
    File,
    Location,
    Organism,
    Organization,
    OrganizationMembership,
    Plasmid,
    ResearchDatabase,
    Strain,
)

AUDITED_MODELS = (Strain, Organism, Location, Plasmid, CustomFieldDefinition, CustomFieldValue, File)


def _resolve_database(instance):
    if hasattr(instance, 'research_database'):
        return instance.research_database
    if hasattr(instance, 'strain') and hasattr(instance.strain, 'research_database'):
        return instance.strain.research_database
    if hasattr(instance, 'field_definition') and hasattr(instance.field_definition, 'research_database'):
        return instance.field_definition.research_database
    return None


def _attach_previous_state(sender, instance):
    if not instance.pk:
        instance._audit_previous_state = None
        return
    previous = sender.objects.filter(pk=instance.pk).first()
    instance._audit_previous_state = get_instance_snapshot(previous) if previous else None


def _build_create_changes(instance):
    snapshot = get_instance_snapshot(instance)
    return {field_name: {'before': None, 'after': value} for field_name, value in snapshot.items()}


def _build_update_changes(instance):
    previous = getattr(instance, '_audit_previous_state', None) or {}
    current = get_instance_snapshot(instance)
    changed = {}
    for field_name, current_value in current.items():
        previous_value = previous.get(field_name)
        if previous_value == current_value:
            continue
        changed[field_name] = {'before': previous_value, 'after': current_value}
    return changed


def _build_delete_changes(instance):
    snapshot = get_instance_snapshot(instance)
    return {field_name: {'before': value, 'after': None} for field_name, value in snapshot.items()}


@receiver(pre_save)
def capture_previous_state(sender, instance, **kwargs):
    if sender not in AUDITED_MODELS:
        return
    _attach_previous_state(sender, instance)


@receiver(post_save)
def audit_save(sender, instance, created, **kwargs):
    if sender not in AUDITED_MODELS:
        return
    if _resolve_database(instance) is None:
        return

    changes = _build_create_changes(instance) if created else _build_update_changes(instance)
    if not changes:
        return

    request_like = type('RequestLike', (), {'user': get_current_user()})()
    log_activity(
        request=request_like,
        instance=instance,
        action='create' if created else 'update',
        changes=changes,
    )


@receiver(post_delete)
def audit_delete(sender, instance, **kwargs):
    if sender not in AUDITED_MODELS:
        return
    if _resolve_database(instance) is None:
        return

    request_like = type('RequestLike', (), {'user': get_current_user()})()
    log_activity(
        request=request_like,
        instance=instance,
        action='delete',
        changes=_build_delete_changes(instance),
    )


@receiver(post_save, sender=ResearchDatabase)
def ensure_creator_owns_database(sender, instance, created, **kwargs):
    if not created or not instance.created_by_id:
        return

    DatabaseMembership.objects.get_or_create(
        user=instance.created_by,
        research_database=instance,
        defaults={'role': DatabaseMembership.Role.OWNER},
    )


@receiver(post_save, sender=Organization)
def ensure_creator_admins_organization(sender, instance, created, **kwargs):
    if not created or not instance.created_by_id:
        return

    OrganizationMembership.objects.get_or_create(
        user=instance.created_by,
        organization=instance,
        defaults={'role': OrganizationMembership.Role.ADMIN},
    )
