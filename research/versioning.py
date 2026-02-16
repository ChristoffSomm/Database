from django.forms.models import model_to_dict

from .models import CustomFieldValue


STANDARD_EXCLUDED_FIELDS = {'created_at', 'updated_at'}


def _serialize_value(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        return [
            _serialize_value(item)
            for item in value
        ]
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value


def serialize_custom_field_values(strain):
    values = (
        CustomFieldValue.objects.filter(strain=strain)
        .select_related('field_definition')
        .order_by('field_definition__name', 'field_definition_id')
    )
    serialized = {}
    for value in values:
        field_type = value.field_definition.field_type
        if field_type == value.field_definition.FieldType.TEXT:
            raw_value = value.value_text
        elif field_type == value.field_definition.FieldType.NUMBER:
            raw_value = value.value_number
        elif field_type == value.field_definition.FieldType.DATE:
            raw_value = value.value_date
        elif field_type == value.field_definition.FieldType.BOOLEAN:
            raw_value = value.value_boolean
        else:
            raw_value = value.value_choice
        serialized[value.field_definition.name] = _serialize_value(raw_value)
    return serialized


def serialize_strain_snapshot(strain):
    standard = model_to_dict(
        strain,
        exclude=tuple(STANDARD_EXCLUDED_FIELDS),
    )
    standard['plasmids'] = sorted(standard.get('plasmids', []))
    serialized_standard = {field_name: _serialize_value(value) for field_name, value in standard.items()}
    serialized_standard['custom_fields'] = serialize_custom_field_values(strain)
    return serialized_standard


def compare_versions(version_a, version_b):
    snapshot_a = version_a.snapshot if hasattr(version_a, 'snapshot') else version_a
    snapshot_b = version_b.snapshot if hasattr(version_b, 'snapshot') else version_b

    fields = set(snapshot_a.keys()) | set(snapshot_b.keys())
    changed_fields = {}
    for field_name in sorted(fields):
        old_value = snapshot_a.get(field_name)
        new_value = snapshot_b.get(field_name)
        if field_name == 'custom_fields':
            old_value = old_value or {}
            new_value = new_value or {}
            custom_names = set(old_value.keys()) | set(new_value.keys())
            for custom_field_name in sorted(custom_names):
                old_custom_value = old_value.get(custom_field_name)
                new_custom_value = new_value.get(custom_field_name)
                if old_custom_value == new_custom_value:
                    continue
                changed_fields[f'custom_fields.{custom_field_name}'] = {
                    'old': old_custom_value,
                    'new': new_custom_value,
                }
            continue

        if old_value == new_value:
            continue
        changed_fields[field_name] = {
            'old': old_value,
            'new': new_value,
        }

    return changed_fields
