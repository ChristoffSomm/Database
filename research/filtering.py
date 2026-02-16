from django.db.models import Q

from .models import CustomFieldDefinition

SUPPORTED_OPERATORS = {'equals', 'contains', 'startswith', 'endswith', 'greater_than', 'less_than'}

STANDARD_FIELD_MAP = {
    'strain_id': ('strain_id', 'text'),
    'name': ('name', 'text'),
    'status': ('status', 'text'),
    'genotype': ('genotype', 'text'),
    'organism': ('organism__name', 'text'),
}


OPERATOR_LOOKUP_SUFFIX = {
    'equals': '',
    'contains': '__icontains',
    'startswith': '__istartswith',
    'endswith': '__iendswith',
    'greater_than': '__gt',
    'less_than': '__lt',
}


def _normalize_filter_definition(filter_definition):
    if not isinstance(filter_definition, dict):
        return [], 'AND'

    conditions = filter_definition.get('conditions')
    logic = str(filter_definition.get('logic', 'AND')).upper()
    if logic not in {'AND', 'OR'}:
        logic = 'AND'

    if not isinstance(conditions, list):
        conditions = []

    return conditions, logic


def _coerce_value(raw_value, value_type):
    if value_type == 'number':
        return float(raw_value)
    if value_type == 'boolean':
        if isinstance(raw_value, bool):
            return raw_value
        return str(raw_value).strip().lower() in {'true', '1', 'yes'}
    return raw_value


def _build_condition_q(field_lookup, operator, raw_value, value_type='text'):
    suffix = OPERATOR_LOOKUP_SUFFIX.get(operator)
    if suffix is None:
        return None

    if value_type in {'number', 'date', 'boolean'} and operator in {'contains', 'startswith', 'endswith'}:
        return None
    if value_type == 'boolean' and operator != 'equals':
        return None

    try:
        value = _coerce_value(raw_value, value_type)
    except (TypeError, ValueError):
        return None

    return Q(**{f'{field_lookup}{suffix}': value})


def apply_filters(queryset, filter_definition):
    """Apply advanced filter definitions to Strain queryset (supports standard + custom fields)."""
    conditions, logic = _normalize_filter_definition(filter_definition)
    if not conditions:
        return queryset

    database_ids = list(queryset.values_list('research_database_id', flat=True).distinct()[:2])
    if len(database_ids) != 1:
        return queryset

    custom_definitions = {
        definition.name: definition
        for definition in CustomFieldDefinition.objects.filter(research_database_id=database_ids[0])
    }

    combined_q = None

    for condition in conditions:
        if not isinstance(condition, dict):
            continue

        field = str(condition.get('field', '')).strip()
        operator = str(condition.get('operator', '')).strip()
        value = condition.get('value')

        if not field or operator not in SUPPORTED_OPERATORS or value in (None, ''):
            continue

        condition_q = None

        if field in STANDARD_FIELD_MAP:
            lookup, value_type = STANDARD_FIELD_MAP[field]
            condition_q = _build_condition_q(lookup, operator, value, value_type)
        else:
            definition = custom_definitions.get(field)
            if definition is not None:
                value_lookup_map = {
                    CustomFieldDefinition.FieldType.TEXT: ('custom_field_values__value_text', 'text'),
                    CustomFieldDefinition.FieldType.NUMBER: ('custom_field_values__value_number', 'number'),
                    CustomFieldDefinition.FieldType.DATE: ('custom_field_values__value_date', 'date'),
                    CustomFieldDefinition.FieldType.BOOLEAN: ('custom_field_values__value_boolean', 'boolean'),
                    CustomFieldDefinition.FieldType.CHOICE: ('custom_field_values__value_choice', 'text'),
                }
                value_lookup, value_type = value_lookup_map[definition.field_type]
                value_q = _build_condition_q(value_lookup, operator, value, value_type)
                if value_q is not None:
                    condition_q = Q(custom_field_values__field_definition=definition) & value_q

        if condition_q is None:
            continue

        if combined_q is None:
            combined_q = condition_q
        elif logic == 'OR':
            combined_q |= condition_q
        else:
            combined_q &= condition_q

    if combined_q is None:
        return queryset

    return queryset.filter(combined_q).distinct()
