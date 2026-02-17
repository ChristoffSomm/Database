import io
import json
import zipfile
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .models import (
    AuditLog,
    CustomFieldDefinition,
    CustomFieldValue,
    DatabaseMembership,
    Location,
    OrganizationMembership,
    Organism,
    Plasmid,
    ResearchDatabase,
    Strain,
    StrainPlasmid,
)

SNAPSHOT_VERSION = '1.0'


def _ts(value):
    return value.isoformat() if value else None


def build_organization_snapshot(organization):
    databases = list(ResearchDatabase.objects.filter(organization=organization).select_related('created_by'))
    database_ids = [database.id for database in databases]
    strains = list(
        Strain.all_objects.filter(research_database_id__in=database_ids)
        .select_related('organism', 'location', 'created_by', 'archived_by')
        .prefetch_related('plasmids')
    )
    strain_ids = [strain.id for strain in strains]
    custom_fields = list(CustomFieldDefinition.objects.filter(research_database_id__in=database_ids).select_related('created_by'))
    field_ids = [field.id for field in custom_fields]

    return {
        'organization': {
            'id': organization.id,
            'uuid': str(organization.uuid),
            'name': organization.name,
            'slug': organization.slug,
            'created_by_id': organization.created_by_id,
            'created_at': _ts(organization.created_at),
        },
        'members': [
            {
                'user_id': membership.user_id,
                'username': membership.user.username,
                'email': membership.user.email,
                'role': membership.role,
                'joined_at': _ts(membership.joined_at),
            }
            for membership in OrganizationMembership.objects.filter(organization=organization).select_related('user')
        ],
        'databases': [
            {
                'id': database.id,
                'name': database.name,
                'description': database.description,
                'created_by_id': database.created_by_id,
                'created_at': _ts(database.created_at),
            }
            for database in databases
        ],
        'database_memberships': [
            {
                'research_database_id': membership.research_database_id,
                'user_id': membership.user_id,
                'username': membership.user.username,
                'email': membership.user.email,
                'role': membership.role,
                'created_at': _ts(membership.created_at),
            }
            for membership in DatabaseMembership.objects.filter(research_database_id__in=database_ids).select_related('user')
        ],
        'organisms': [
            {'id': organism.id, 'research_database_id': organism.research_database_id, 'name': organism.name}
            for organism in Organism.objects.filter(research_database_id__in=database_ids)
        ],
        'locations': [
            {
                'id': location.id,
                'research_database_id': location.research_database_id,
                'building': location.building,
                'room': location.room,
                'freezer': location.freezer,
                'box': location.box,
                'position': location.position,
            }
            for location in Location.objects.filter(research_database_id__in=database_ids)
        ],
        'plasmids': [
            {
                'id': plasmid.id,
                'research_database_id': plasmid.research_database_id,
                'name': plasmid.name,
                'resistance_marker': plasmid.resistance_marker,
                'notes': plasmid.notes,
            }
            for plasmid in Plasmid.objects.filter(research_database_id__in=database_ids)
        ],
        'strains': [
            {
                'id': strain.id,
                'research_database_id': strain.research_database_id,
                'strain_id': strain.strain_id,
                'name': strain.name,
                'organism_id': strain.organism_id,
                'genotype': strain.genotype,
                'selective_marker': strain.selective_marker,
                'comments': strain.comments,
                'location_id': strain.location_id,
                'status': strain.status,
                'created_by_id': strain.created_by_id,
                'created_at': _ts(strain.created_at),
                'updated_at': _ts(strain.updated_at),
                'is_active': strain.is_active,
                'is_archived': strain.is_archived,
                'archived_at': _ts(strain.archived_at),
                'archived_by_id': strain.archived_by_id,
            }
            for strain in strains
        ],
        'strain_plasmids': [
            {'strain_id': relation.strain_id, 'plasmid_id': relation.plasmid_id}
            for relation in StrainPlasmid.objects.filter(strain_id__in=strain_ids)
        ],
        'custom_fields': [
            {
                'id': field.id,
                'research_database_id': field.research_database_id,
                'name': field.name,
                'field_type': field.field_type,
                'choices': field.choices,
                'created_by_id': field.created_by_id,
                'created_at': _ts(field.created_at),
            }
            for field in custom_fields
        ],
        'field_values': [
            {
                'strain_id': value.strain_id,
                'field_definition_id': value.field_definition_id,
                'value_text': value.value_text,
                'value_number': value.value_number,
                'value_date': value.value_date.isoformat() if value.value_date else None,
                'value_boolean': value.value_boolean,
                'value_choice': value.value_choice,
            }
            for value in CustomFieldValue.objects.filter(strain_id__in=strain_ids, field_definition_id__in=field_ids)
        ],
        'audit_logs': [
            {
                'database_id': log.database_id,
                'user_id': log.user_id,
                'action': log.action,
                'object_type': log.object_type,
                'object_id': log.object_id,
                'metadata': log.metadata,
                'timestamp': _ts(log.timestamp),
            }
            for log in AuditLog.objects.filter(database_id__in=database_ids)
        ],
        'exported_at': timezone.now().isoformat(),
        'version': SNAPSHOT_VERSION,
    }


def make_snapshot_zip(snapshot):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr('snapshot.json', json.dumps(snapshot, indent=2, default=str))
    zip_buffer.seek(0)
    return zip_buffer


def _resolve_user(users_by_id, users_by_name, users_by_email, user_id, username, email, fallback):
    return users_by_id.get(user_id) or users_by_name.get(username) or users_by_email.get(email) or fallback


def restore_organization_snapshot(*, organization, snapshot, acting_user, users_queryset):
    if snapshot.get('version') != SNAPSHOT_VERSION:
        raise ValueError('Unsupported snapshot version.')

    snapshot_org = snapshot.get('organization', {})
    if str(snapshot_org.get('uuid')) != str(organization.uuid):
        raise ValueError('Snapshot organization does not match target organization.')

    users_by_id = {user.id: user for user in users_queryset}
    users_by_name = {user.username: user for user in users_queryset}
    users_by_email = {user.email: user for user in users_queryset if user.email}

    database_id_map = {}
    organism_id_map = {}
    location_id_map = {}
    plasmid_id_map = {}
    strain_id_map = {}
    field_id_map = {}

    with transaction.atomic():
        CustomFieldValue.objects.filter(strain__research_database__organization=organization).delete()
        Strain.all_objects.filter(research_database__organization=organization).delete()
        CustomFieldDefinition.objects.filter(research_database__organization=organization).delete()
        AuditLog.objects.filter(database__organization=organization).delete()
        DatabaseMembership.objects.filter(research_database__organization=organization).delete()
        Organism.objects.filter(research_database__organization=organization).delete()
        Location.objects.filter(research_database__organization=organization).delete()
        Plasmid.objects.filter(research_database__organization=organization).delete()
        ResearchDatabase.objects.filter(organization=organization).delete()

        organization.name = snapshot_org.get('name', organization.name)
        organization.slug = snapshot_org.get('slug', organization.slug)
        organization.save(update_fields=['name', 'slug'])

        for member_data in snapshot.get('members', []):
            member_user = _resolve_user(
                users_by_id,
                users_by_name,
                users_by_email,
                member_data.get('user_id'),
                member_data.get('username'),
                member_data.get('email'),
                acting_user,
            )
            OrganizationMembership.objects.update_or_create(
                organization=organization,
                user=member_user,
                defaults={'role': member_data.get('role', OrganizationMembership.Role.MEMBER)},
            )

        for database_data in snapshot.get('databases', []):
            created_by = _resolve_user(
                users_by_id,
                users_by_name,
                users_by_email,
                database_data.get('created_by_id'),
                None,
                None,
                acting_user,
            )
            database = ResearchDatabase.objects.create(
                organization=organization,
                name=database_data['name'],
                description=database_data.get('description', ''),
                created_by=created_by,
            )
            database_id_map[database_data['id']] = database

        for membership_data in snapshot.get('database_memberships', []):
            database = database_id_map.get(membership_data.get('research_database_id'))
            if not database:
                continue
            membership_user = _resolve_user(
                users_by_id,
                users_by_name,
                users_by_email,
                membership_data.get('user_id'),
                membership_data.get('username'),
                membership_data.get('email'),
                acting_user,
            )
            DatabaseMembership.objects.update_or_create(
                research_database=database,
                user=membership_user,
                defaults={'role': membership_data.get('role', DatabaseMembership.Role.VIEWER)},
            )

        for organism_data in snapshot.get('organisms', []):
            database = database_id_map.get(organism_data.get('research_database_id'))
            if not database:
                continue
            organism = Organism.objects.create(research_database=database, name=organism_data['name'])
            organism_id_map[organism_data['id']] = organism

        for location_data in snapshot.get('locations', []):
            database = database_id_map.get(location_data.get('research_database_id'))
            if not database:
                continue
            location = Location.objects.create(
                research_database=database,
                building=location_data['building'],
                room=location_data['room'],
                freezer=location_data['freezer'],
                box=location_data['box'],
                position=location_data['position'],
            )
            location_id_map[location_data['id']] = location

        for plasmid_data in snapshot.get('plasmids', []):
            database = database_id_map.get(plasmid_data.get('research_database_id'))
            if not database:
                continue
            plasmid = Plasmid.objects.create(
                research_database=database,
                name=plasmid_data['name'],
                resistance_marker=plasmid_data.get('resistance_marker', ''),
                notes=plasmid_data.get('notes', ''),
            )
            plasmid_id_map[plasmid_data['id']] = plasmid

        for strain_data in snapshot.get('strains', []):
            database = database_id_map.get(strain_data.get('research_database_id'))
            organism = organism_id_map.get(strain_data.get('organism_id'))
            location = location_id_map.get(strain_data.get('location_id'))
            if not database or not organism or not location:
                continue
            created_by = _resolve_user(
                users_by_id,
                users_by_name,
                users_by_email,
                strain_data.get('created_by_id'),
                None,
                None,
                acting_user,
            )
            archived_by = _resolve_user(
                users_by_id,
                users_by_name,
                users_by_email,
                strain_data.get('archived_by_id'),
                None,
                None,
                None,
            )
            strain = Strain.all_objects.create(
                research_database=database,
                strain_id=strain_data['strain_id'],
                name=strain_data['name'],
                organism=organism,
                genotype=strain_data.get('genotype', ''),
                selective_marker=strain_data.get('selective_marker', ''),
                comments=strain_data.get('comments', ''),
                location=location,
                status=strain_data.get('status', Strain.Status.DRAFT),
                created_by=created_by,
                is_active=strain_data.get('is_active', True),
                is_archived=strain_data.get('is_archived', False),
                archived_by=archived_by,
                archived_at=parse_datetime(strain_data['archived_at']) if strain_data.get('archived_at') else None,
            )
            strain_id_map[strain_data['id']] = strain

        for relation_data in snapshot.get('strain_plasmids', []):
            strain = strain_id_map.get(relation_data.get('strain_id'))
            plasmid = plasmid_id_map.get(relation_data.get('plasmid_id'))
            if strain and plasmid:
                StrainPlasmid.objects.get_or_create(strain=strain, plasmid=plasmid)

        for field_data in snapshot.get('custom_fields', []):
            database = database_id_map.get(field_data.get('research_database_id'))
            if not database:
                continue
            created_by = _resolve_user(
                users_by_id,
                users_by_name,
                users_by_email,
                field_data.get('created_by_id'),
                None,
                None,
                acting_user,
            )
            field = CustomFieldDefinition.objects.create(
                research_database=database,
                name=field_data['name'],
                field_type=field_data['field_type'],
                choices=field_data.get('choices', ''),
                created_by=created_by,
            )
            field_id_map[field_data['id']] = field

        for value_data in snapshot.get('field_values', []):
            strain = strain_id_map.get(value_data.get('strain_id'))
            field = field_id_map.get(value_data.get('field_definition_id'))
            if not strain or not field:
                continue
            CustomFieldValue.objects.update_or_create(
                strain=strain,
                field_definition=field,
                defaults={
                    'value_text': value_data.get('value_text'),
                    'value_number': value_data.get('value_number'),
                    'value_date': parse_date(value_data['value_date']) if value_data.get('value_date') else None,
                    'value_boolean': value_data.get('value_boolean'),
                    'value_choice': value_data.get('value_choice'),
                },
            )

        for log_data in snapshot.get('audit_logs', []):
            database = database_id_map.get(log_data.get('database_id'))
            log_user = _resolve_user(
                users_by_id,
                users_by_name,
                users_by_email,
                log_data.get('user_id'),
                None,
                None,
                None,
            )
            AuditLog.objects.create(
                database=database,
                user=log_user,
                action=log_data.get('action', 'restored'),
                object_type=log_data.get('object_type', ''),
                object_id=log_data.get('object_id'),
                metadata=log_data.get('metadata', {}),
            )

        AuditLog.objects.create(
            database=None,
            user=acting_user,
            action='organization_snapshot_restore',
            object_type='Organization',
            object_id=organization.id,
            metadata={
                'organization_uuid': str(organization.uuid),
                'restored_at': datetime.utcnow().isoformat(),
                'version': snapshot.get('version'),
            },
        )
