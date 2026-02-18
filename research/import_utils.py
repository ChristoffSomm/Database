import csv
import io
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction

from .models import AuditLog, CustomFieldDefinition, CustomFieldValue, Organism, Plasmid, Strain

STANDARD_IMPORT_FIELDS = [
    ('strain_id', 'Strain ID'),
    ('location', 'Location'),
    ('organism', 'Organism'),
    ('genotype', 'Genotype'),
    ('plasmids', 'Plasmids'),
    ('selective_marker', 'Selective marker'),
    ('comments', 'Comments'),
]
REQUIRED_IMPORT_FIELDS = ['strain_id', 'organism', 'genotype', 'location']


def parse_csv_upload(uploaded_file):
    content = uploaded_file.read()
    if isinstance(content, bytes):
        content = content.decode('utf-8-sig')

    csv_stream = io.StringIO(content)
    reader = csv.DictReader(csv_stream)
    if not reader.fieldnames:
        raise ValidationError('CSV file must include a header row.')

    headers = [header.strip() for header in reader.fieldnames if header is not None]
    rows = [{(k or '').strip(): (v or '').strip() for k, v in row.items()} for row in reader]
    return headers, rows


def parse_location_value(raw_value):
    if not raw_value:
        return None
    value = raw_value.strip()
    return value if value.startswith('Box ') else None


def parse_custom_field_value(definition, raw_value):
    value = (raw_value or '').strip()
    if value == '':
        return None, None

    if definition.field_type == CustomFieldDefinition.FieldType.TEXT:
        return 'value_text', value
    if definition.field_type == CustomFieldDefinition.FieldType.NUMBER:
        try:
            return 'value_number', float(value)
        except ValueError:
            return None, f'Invalid number for custom field "{definition.name}".'
    if definition.field_type == CustomFieldDefinition.FieldType.DATE:
        try:
            return 'value_date', datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            return None, f'Invalid date for custom field "{definition.name}". Use YYYY-MM-DD.'
    if definition.field_type == CustomFieldDefinition.FieldType.BOOLEAN:
        truthy = {'true', '1', 'yes', 'y'}
        falsy = {'false', '0', 'no', 'n'}
        lowered = value.lower()
        if lowered in truthy:
            return 'value_boolean', True
        if lowered in falsy:
            return 'value_boolean', False
        return None, f'Invalid boolean for custom field "{definition.name}".'
    if definition.field_type == CustomFieldDefinition.FieldType.CHOICE:
        valid = set(definition.parsed_choices())
        if value not in valid:
            return None, f'Invalid choice for custom field "{definition.name}".'
        return 'value_choice', value
    return None, None


def validate_import_row(mapped_row, active_database, custom_definitions_by_name):
    errors = []

    for required in REQUIRED_IMPORT_FIELDS:
        if not mapped_row.get(required):
            errors.append(f'Missing required field: {required}.')

    location_string = mapped_row.get('location')
    if location_string and not parse_location_value(location_string):
        errors.append('Location must be in "Box <number> <row><column>" format.')

    for field_name, raw_value in mapped_row.items():
        if field_name.startswith('custom:'):
            definition_name = field_name.split(':', 1)[1]
            definition = custom_definitions_by_name.get(definition_name)
            if definition is None:
                errors.append(f'Unknown custom field mapping: {definition_name}.')
                continue
            _, custom_error = parse_custom_field_value(definition, raw_value)
            if custom_error:
                errors.append(custom_error)

    return errors


def resolve_fk(model, database, value, field_name='name'):
    """Resolve a database-scoped related object by name, auto-creating when needed.

    Uses case-insensitive matching and retries lookup on integrity collisions to
    avoid duplicates under concurrent imports.
    """

    if not value:
        return None

    normalized_value = value.strip()
    if not normalized_value:
        return None

    database_filter = {'research_database': database}
    lookup = {f'{field_name}__iexact': normalized_value}

    existing = model.objects.filter(**database_filter, **lookup).first()
    if existing:
        return existing

    try:
        return model.objects.create(**database_filter, **{field_name: normalized_value})
    except IntegrityError:
        return model.objects.filter(**database_filter, **lookup).first()


def get_import_row_warnings(mapped_row, active_database):
    warnings = []
    organism_name = (mapped_row.get('organism') or '').strip()
    if organism_name and not Organism.objects.filter(research_database=active_database, name__iexact=organism_name).exists():
        warnings.append('Organism auto-created during import')
    return warnings


def build_mapped_rows(rows, column_mapping):
    mapped_rows = []
    for row in rows:
        mapped_row = {}
        for csv_column, mapped_field in column_mapping.items():
            if not mapped_field:
                continue
            mapped_row[mapped_field] = (row.get(csv_column) or '').strip()
        mapped_rows.append(mapped_row)
    return mapped_rows


def import_strains_from_csv_rows(*, active_database, user, mapped_rows, custom_definitions_by_name):
    created_count = 0
    skipped_count = 0

    with transaction.atomic():
        for mapped_row in mapped_rows:
            try:
                with transaction.atomic():
                    strain_id = (mapped_row.get('strain_id') or '').strip()
                    if not strain_id:
                        skipped_count += 1
                        continue

                    if Strain.all_objects.filter(research_database=active_database, strain_id__iexact=strain_id).exists():
                        skipped_count += 1
                        continue

                    validation_errors = validate_import_row(mapped_row, active_database, custom_definitions_by_name)
                    if validation_errors:
                        skipped_count += 1
                        continue

                    location = parse_location_value(mapped_row['location'])
                    if location is None:
                        skipped_count += 1
                        continue

                    organism_name = (mapped_row.get('organism') or '').strip()
                    organism_exists = Organism.objects.filter(
                        research_database=active_database,
                        name__iexact=organism_name,
                    ).exists()
                    organism = resolve_fk(Organism, active_database, organism_name)
                    if organism is None:
                        skipped_count += 1
                        continue

                    if not organism_exists:
                        AuditLog.objects.create(
                            database=active_database,
                            user=user,
                            action='AUTO_CREATE_ORGANISM',
                            object_type='Organism',
                            object_id=organism.id,
                            metadata={'organism': organism.name},
                        )

                    strain = Strain.objects.create(
                        research_database=active_database,
                        strain_id=strain_id,
                        name=strain_id,
                        organism=organism.name,
                        genotype=(mapped_row.get('genotype') or '').strip(),
                        selective_marker=(mapped_row.get('selective_marker') or '').strip(),
                        comments=(mapped_row.get('comments') or '').strip(),
                        location=location,
                        created_by=user,
                    )

                    plasmids_value = (mapped_row.get('plasmids') or '').strip()
                    if plasmids_value:
                        plasmid_names = [name.strip() for name in plasmids_value.split(',') if name.strip()]
                        for plasmid_name in plasmid_names:
                            plasmid = resolve_fk(Plasmid, active_database, plasmid_name)
                            if plasmid:
                                strain.plasmids.add(plasmid)

                    for field_name, raw_value in mapped_row.items():
                        if not field_name.startswith('custom:'):
                            continue
                        definition_name = field_name.split(':', 1)[1]
                        definition = custom_definitions_by_name.get(definition_name)
                        if not definition:
                            continue
                        value_attr, parsed_value = parse_custom_field_value(definition, raw_value)
                        if not value_attr:
                            continue
                        custom_value, _ = CustomFieldValue.objects.get_or_create(strain=strain, field_definition=definition)
                        custom_value.value_text = None
                        custom_value.value_number = None
                        custom_value.value_date = None
                        custom_value.value_boolean = None
                        custom_value.value_choice = None
                        setattr(custom_value, value_attr, parsed_value)
                        custom_value.save()

                    created_count += 1
            except Exception:  # noqa: BLE001
                skipped_count += 1
                continue

    return created_count, skipped_count
