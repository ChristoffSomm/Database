from decimal import Decimal

from django import forms
from django.contrib.contenttypes.models import ContentType

from .models import CustomFieldDefinition, CustomFieldValue, DatabaseMembership, Location, Organism, Plasmid


def _role_for_user(user, research_database):
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    membership = DatabaseMembership.objects.filter(user=user, research_database=research_database).first()
    return membership.role if membership else None


def evaluate_condition_logic(logic, values):
    if not logic:
        return True
    operator = (logic.get('operator') or 'AND').upper()
    conditions = logic.get('conditions') or []
    results = []
    for condition in conditions:
        field_key = condition.get('field')
        op = (condition.get('operator') or 'equals').lower()
        expected = condition.get('value')
        actual = values.get(field_key) or values.get(f'custom_{field_key}')
        if hasattr(actual, 'pk'):
            actual = actual.pk
        if op == 'equals':
            results.append(actual == expected)
        elif op == 'not_equals':
            results.append(actual != expected)
        elif op == 'contains':
            if isinstance(actual, (list, tuple, set)):
                results.append(expected in actual)
            else:
                results.append(str(expected) in str(actual or ''))
        elif op == 'gt':
            results.append(actual is not None and actual > expected)
        elif op == 'lt':
            results.append(actual is not None and actual < expected)
        else:
            results.append(False)
    return all(results) if operator == 'AND' else any(results)


def _lookup_factory(definition):
    ft = definition.field_type
    if ft in {CustomFieldDefinition.FieldType.TEXT, CustomFieldDefinition.FieldType.LONG_TEXT}:
        return lambda value: {'value_text': value} if ft == CustomFieldDefinition.FieldType.TEXT else {'value_long_text': value}
    if ft in {CustomFieldDefinition.FieldType.INTEGER, CustomFieldDefinition.FieldType.NUMBER}:
        return lambda value: {'value_integer': value}
    if ft == CustomFieldDefinition.FieldType.DECIMAL:
        return lambda value: {'value_decimal': value}
    if ft == CustomFieldDefinition.FieldType.BOOLEAN:
        return lambda value: {'value_boolean': bool(value)}
    if ft in {CustomFieldDefinition.FieldType.SINGLE_SELECT, CustomFieldDefinition.FieldType.CHOICE}:
        return lambda value: {'value_single_select': value}
    if ft == CustomFieldDefinition.FieldType.MULTI_SELECT:
        return lambda value: {'value_multi_select': value}
    if ft == CustomFieldDefinition.FieldType.DATE:
        return lambda value: {'value_date': value}
    if ft == CustomFieldDefinition.FieldType.URL:
        return lambda value: {'value_url': value}
    if ft == CustomFieldDefinition.FieldType.EMAIL:
        return lambda value: {'value_email': value}
    if ft == CustomFieldDefinition.FieldType.FOREIGN_KEY:
        return lambda value: {'value_fk_object_id': value.pk}
    return lambda value: {}


def build_dynamic_custom_fields(form, database, instance, user):
    if not database:
        return []
    definitions = CustomFieldDefinition.objects.filter(research_database=database).select_related('group').order_by('group__order', 'order', 'id')
    existing = {}
    if instance and instance.pk:
        existing = {v.field_definition_id: v for v in instance.custom_field_values.select_related('field_definition', 'value_fk_content_type')}
    role = _role_for_user(user, database)
    field_entries = []

    for definition in definitions:
        if definition.visible_to_roles and role not in definition.visible_to_roles:
            continue
        field_name = f'custom_{definition.key}'
        required = bool(definition.validation_rules.get('required', False))
        editable = not definition.editable_to_roles or role in definition.editable_to_roles
        help_text = definition.help_text or ''

        kwargs = {'required': required, 'label': definition.label, 'help_text': help_text}
        ft = definition.field_type
        if ft == CustomFieldDefinition.FieldType.TEXT:
            field = forms.CharField(**kwargs)
        elif ft == CustomFieldDefinition.FieldType.LONG_TEXT:
            field = forms.CharField(widget=forms.Textarea(attrs={'rows': 4}), **kwargs)
        elif ft in {CustomFieldDefinition.FieldType.INTEGER, CustomFieldDefinition.FieldType.NUMBER}:
            field = forms.IntegerField(**kwargs)
        elif ft == CustomFieldDefinition.FieldType.DECIMAL:
            field = forms.DecimalField(**kwargs)
        elif ft == CustomFieldDefinition.FieldType.BOOLEAN:
            field = forms.BooleanField(required=False, label=definition.label, help_text=help_text)
        elif ft == CustomFieldDefinition.FieldType.DATE:
            field = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), **kwargs)
        elif ft in {CustomFieldDefinition.FieldType.SINGLE_SELECT, CustomFieldDefinition.FieldType.CHOICE}:
            field = forms.ChoiceField(choices=[('', '---------')] + [(c, c) for c in definition.parsed_choices()], **kwargs)
        elif ft == CustomFieldDefinition.FieldType.MULTI_SELECT:
            field = forms.MultipleChoiceField(choices=[(c, c) for c in definition.parsed_choices()], required=required, label=definition.label, help_text=help_text)
        elif ft == CustomFieldDefinition.FieldType.URL:
            field = forms.URLField(**kwargs)
        elif ft == CustomFieldDefinition.FieldType.EMAIL:
            field = forms.EmailField(**kwargs)
        elif ft == CustomFieldDefinition.FieldType.FILE:
            field = forms.FileField(**kwargs)
        elif ft == CustomFieldDefinition.FieldType.FOREIGN_KEY:
            model_map = {
                CustomFieldDefinition.RelatedModel.ORGANISM: Organism,
                CustomFieldDefinition.RelatedModel.PLASMID: Plasmid,
                CustomFieldDefinition.RelatedModel.LOCATION: Location,
            }
            model = model_map.get(definition.related_model)
            queryset = model.objects.filter(research_database=database).order_by('id') if model else Organism.objects.none()
            field = forms.ModelChoiceField(queryset=queryset, **kwargs)
        else:
            continue

        if not editable:
            field.disabled = True
        form.fields[field_name] = field

        existing_value = existing.get(definition.id)
        if existing_value:
            form.initial[field_name] = existing_value.display_value
        elif definition.default_value:
            form.initial[field_name] = definition.default_value.get('value')

        field.widget.attrs['data-custom-key'] = definition.key
        field.widget.attrs['data-conditional-logic'] = definition.conditional_logic or {}
        field.widget.attrs['data-group'] = definition.group.name if definition.group_id else ''
        field_entries.append({'definition': definition, 'field_name': field_name, 'unique_lookup': _lookup_factory(definition)})

    return field_entries


def save_dynamic_custom_values(form, strain, field_entries):
    for entry in field_entries:
        definition = entry['definition']
        field_name = entry['field_name']
        value = form.cleaned_data.get(field_name)
        if value in (None, '', []):
            CustomFieldValue.objects.filter(strain=strain, field_definition=definition).delete()
            continue

        custom_value, _ = CustomFieldValue.objects.get_or_create(strain=strain, field_definition=definition)
        custom_value.value_text = None
        custom_value.value_long_text = None
        custom_value.value_number = None
        custom_value.value_integer = None
        custom_value.value_decimal = None
        custom_value.value_date = None
        custom_value.value_boolean = None
        custom_value.value_choice = None
        custom_value.value_single_select = None
        custom_value.value_multi_select = []
        custom_value.value_fk_content_type = None
        custom_value.value_fk_object_id = None
        custom_value.value_url = None
        custom_value.value_email = None

        ft = definition.field_type
        if ft == CustomFieldDefinition.FieldType.TEXT:
            custom_value.value_text = str(value).strip()
        elif ft == CustomFieldDefinition.FieldType.LONG_TEXT:
            custom_value.value_long_text = str(value).strip()
        elif ft in {CustomFieldDefinition.FieldType.INTEGER, CustomFieldDefinition.FieldType.NUMBER}:
            custom_value.value_integer = int(value)
            custom_value.value_number = float(value)
        elif ft == CustomFieldDefinition.FieldType.DECIMAL:
            custom_value.value_decimal = Decimal(str(value))
        elif ft == CustomFieldDefinition.FieldType.DATE:
            custom_value.value_date = value
        elif ft == CustomFieldDefinition.FieldType.BOOLEAN:
            custom_value.value_boolean = bool(value)
        elif ft in {CustomFieldDefinition.FieldType.SINGLE_SELECT, CustomFieldDefinition.FieldType.CHOICE}:
            custom_value.value_single_select = value
            custom_value.value_choice = value
        elif ft == CustomFieldDefinition.FieldType.MULTI_SELECT:
            custom_value.value_multi_select = list(value)
        elif ft == CustomFieldDefinition.FieldType.URL:
            custom_value.value_url = value
        elif ft == CustomFieldDefinition.FieldType.EMAIL:
            custom_value.value_email = value
        elif ft == CustomFieldDefinition.FieldType.FILE:
            custom_value.value_file = value
        elif ft == CustomFieldDefinition.FieldType.FOREIGN_KEY and value:
            custom_value.value_fk_content_type = ContentType.objects.get_for_model(value.__class__)
            custom_value.value_fk_object_id = value.pk

        custom_value.save()
