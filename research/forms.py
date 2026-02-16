from django import forms

from .helpers import get_active_database, get_custom_field_definitions
from .models import CustomFieldDefinition, CustomFieldValue, Location, Organism, Plasmid, SavedView, Strain


class GlobalSearchForm(forms.Form):
    q = forms.CharField(max_length=200, required=False, strip=True)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            if not data:
                raise forms.ValidationError('Please choose at least one file to upload.')
            return [single_file_clean(item, initial) for item in data]
        return [single_file_clean(data, initial)]


class CustomFieldDefinitionForm(forms.ModelForm):
    class Meta:
        model = CustomFieldDefinition
        fields = ['name', 'field_type', 'choices']

    def clean(self):
        cleaned_data = super().clean()
        field_type = cleaned_data.get('field_type')
        choices = (cleaned_data.get('choices') or '').strip()
        if field_type == CustomFieldDefinition.FieldType.CHOICE and not choices:
            self.add_error('choices', 'Choices are required for choice fields.')
        if field_type != CustomFieldDefinition.FieldType.CHOICE:
            cleaned_data['choices'] = ''
        return cleaned_data


class SavedViewForm(forms.ModelForm):
    class Meta:
        model = SavedView
        fields = ['name', 'is_shared']

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise forms.ValidationError('View name is required.')
        return name


class StrainForm(forms.ModelForm):
    class Meta:
        model = Strain
        fields = ['strain_id', 'name', 'organism', 'genotype', 'plasmids', 'selective_marker', 'comments', 'location', 'status']
        widgets = {
            'genotype': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        self.custom_field_definitions = []
        self.custom_field_names = []

        current_database = self._get_current_database()
        if current_database:
            self.fields['organism'].queryset = Organism.objects.filter(research_database=current_database).order_by('name')
            self.fields['plasmids'].queryset = Plasmid.objects.filter(research_database=current_database).order_by('name')
            self.fields['location'].queryset = Location.objects.filter(research_database=current_database).order_by(
                'building', 'room', 'freezer', 'box', 'position'
            )
        else:
            self.fields['organism'].queryset = Organism.objects.none()
            self.fields['plasmids'].queryset = Plasmid.objects.none()
            self.fields['location'].queryset = Location.objects.none()

        self._add_dynamic_custom_fields(current_database)

    def _get_current_database(self):
        if not self.request:
            return None
        return getattr(self.request, 'active_database', None) or get_active_database(self.request)

    def _custom_field_name(self, definition_id):
        return f'custom_field_{definition_id}'

    def _add_dynamic_custom_fields(self, current_database):
        definitions = list(get_custom_field_definitions(current_database))
        existing_values = {}
        if self.instance and self.instance.pk:
            existing_values = {
                value.field_definition_id: value
                for value in self.instance.custom_field_values.select_related('field_definition')
            }

        for definition in definitions:
            field_name = self._custom_field_name(definition.id)
            self.custom_field_definitions.append(definition)
            self.custom_field_names.append(field_name)
            if definition.field_type == CustomFieldDefinition.FieldType.TEXT:
                self.fields[field_name] = forms.CharField(required=False, label=definition.name)
                if definition.id in existing_values:
                    self.initial[field_name] = existing_values[definition.id].value_text
            elif definition.field_type == CustomFieldDefinition.FieldType.NUMBER:
                self.fields[field_name] = forms.FloatField(required=False, label=definition.name)
                if definition.id in existing_values:
                    self.initial[field_name] = existing_values[definition.id].value_number
            elif definition.field_type == CustomFieldDefinition.FieldType.DATE:
                self.fields[field_name] = forms.DateField(required=False, label=definition.name, widget=forms.DateInput(attrs={'type': 'date'}))
                if definition.id in existing_values:
                    self.initial[field_name] = existing_values[definition.id].value_date
            elif definition.field_type == CustomFieldDefinition.FieldType.BOOLEAN:
                self.fields[field_name] = forms.BooleanField(required=False, label=definition.name)
                if definition.id in existing_values:
                    self.initial[field_name] = bool(existing_values[definition.id].value_boolean)
            elif definition.field_type == CustomFieldDefinition.FieldType.CHOICE:
                choices = [('', '---------')] + [(choice, choice) for choice in definition.parsed_choices()]
                self.fields[field_name] = forms.ChoiceField(required=False, label=definition.name, choices=choices)
                if definition.id in existing_values:
                    self.initial[field_name] = existing_values[definition.id].value_choice

    def clean_strain_id(self):
        strain_id = self.cleaned_data['strain_id'].strip()
        if not strain_id:
            raise forms.ValidationError('Strain ID is required.')

        current_database = self._get_current_database()
        queryset = Strain.objects.filter(research_database=current_database, strain_id__iexact=strain_id)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('A strain with this ID already exists in the current database.')
        return strain_id

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError('Name is required.')
        return name

    def clean(self):
        cleaned_data = super().clean()
        current_database = self._get_current_database()
        if current_database is None:
            raise forms.ValidationError('No active research database selected.')

        for field_name in ('organism', 'location'):
            instance = cleaned_data.get(field_name)
            if instance and instance.research_database_id != current_database.id:
                self.add_error(field_name, 'Selected item does not belong to the current database.')

        plasmids = cleaned_data.get('plasmids')
        if plasmids is not None:
            invalid_plasmids = [plasmid for plasmid in plasmids if plasmid.research_database_id != current_database.id]
            if invalid_plasmids:
                self.add_error('plasmids', 'One or more selected plasmids are not in the current database.')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        current_database = self._get_current_database()
        if current_database:
            instance.research_database = current_database
        if commit:
            instance.save()
            self.save_m2m()
            self.save_custom_field_values(instance)
        return instance

    def save_custom_field_values(self, strain):
        for definition in self.custom_field_definitions:
            field_name = self._custom_field_name(definition.id)
            submitted_value = self.cleaned_data.get(field_name)
            is_empty = submitted_value in (None, '')
            if definition.field_type == CustomFieldDefinition.FieldType.TEXT and isinstance(submitted_value, str):
                submitted_value = submitted_value.strip()
                is_empty = submitted_value == ''

            if is_empty and definition.field_type != CustomFieldDefinition.FieldType.BOOLEAN:
                CustomFieldValue.objects.filter(strain=strain, field_definition=definition).delete()
                continue

            custom_value, _ = CustomFieldValue.objects.get_or_create(strain=strain, field_definition=definition)
            custom_value.value_text = None
            custom_value.value_number = None
            custom_value.value_date = None
            custom_value.value_boolean = None
            custom_value.value_choice = None

            if definition.field_type == CustomFieldDefinition.FieldType.TEXT:
                custom_value.value_text = submitted_value
            elif definition.field_type == CustomFieldDefinition.FieldType.NUMBER:
                custom_value.value_number = submitted_value
            elif definition.field_type == CustomFieldDefinition.FieldType.DATE:
                custom_value.value_date = submitted_value
            elif definition.field_type == CustomFieldDefinition.FieldType.BOOLEAN:
                custom_value.value_boolean = bool(submitted_value)
            elif definition.field_type == CustomFieldDefinition.FieldType.CHOICE:
                custom_value.value_choice = submitted_value

            custom_value.save()


class StrainAttachmentUploadForm(forms.Form):
    files = MultipleFileField(
        label='Select files',
        widget=MultipleFileInput(attrs={'multiple': True}),
        required=True,
    )


class BulkEditStrainsForm(forms.Form):
    organism = forms.ModelChoiceField(queryset=Organism.objects.none(), required=False)
    location = forms.ModelChoiceField(queryset=Location.objects.none(), required=False)
    genotype = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
    plasmids = forms.ModelMultipleChoiceField(queryset=Plasmid.objects.none(), required=False)
    selective_marker = forms.CharField(required=False)
    comments = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        self.custom_field_definitions = list(get_custom_field_definitions(self._get_current_database()))

        current_database = self._get_current_database()
        if current_database:
            self.fields['organism'].queryset = Organism.objects.filter(research_database=current_database).order_by('name')
            self.fields['location'].queryset = Location.objects.filter(research_database=current_database).order_by(
                'building', 'room', 'freezer', 'box', 'position'
            )
            self.fields['plasmids'].queryset = Plasmid.objects.filter(research_database=current_database).order_by('name')

        self._add_dynamic_custom_fields()

    def _get_current_database(self):
        if not self.request:
            return None
        return getattr(self.request, 'active_database', None) or get_active_database(self.request)

    def _custom_field_name(self, definition_id):
        return f'bulk_custom_field_{definition_id}'

    def _add_dynamic_custom_fields(self):
        for definition in self.custom_field_definitions:
            field_name = self._custom_field_name(definition.id)
            if definition.field_type == CustomFieldDefinition.FieldType.TEXT:
                self.fields[field_name] = forms.CharField(required=False, label=definition.name)
            elif definition.field_type == CustomFieldDefinition.FieldType.NUMBER:
                self.fields[field_name] = forms.FloatField(required=False, label=definition.name)
            elif definition.field_type == CustomFieldDefinition.FieldType.DATE:
                self.fields[field_name] = forms.DateField(required=False, label=definition.name, widget=forms.DateInput(attrs={'type': 'date'}))
            elif definition.field_type == CustomFieldDefinition.FieldType.BOOLEAN:
                self.fields[field_name] = forms.TypedChoiceField(
                    required=False,
                    label=definition.name,
                    choices=[('', 'No change'), ('true', 'Yes'), ('false', 'No')],
                    coerce=lambda value: {'true': True, 'false': False}.get(value),
                )
            elif definition.field_type == CustomFieldDefinition.FieldType.CHOICE:
                choices = [('', 'No change')] + [(choice, choice) for choice in definition.parsed_choices()]
                self.fields[field_name] = forms.ChoiceField(required=False, label=definition.name, choices=choices)

    def clean(self):
        cleaned_data = super().clean()
        current_database = self._get_current_database()
        if current_database is None:
            raise forms.ValidationError('No active research database selected.')

        for field_name in ('organism', 'location'):
            instance = cleaned_data.get(field_name)
            if instance and instance.research_database_id != current_database.id:
                self.add_error(field_name, 'Selected item does not belong to the current database.')

        plasmids = cleaned_data.get('plasmids')
        if plasmids is not None:
            invalid_plasmids = [plasmid for plasmid in plasmids if plasmid.research_database_id != current_database.id]
            if invalid_plasmids:
                self.add_error('plasmids', 'One or more selected plasmids are not in the current database.')

        return cleaned_data

    def get_updated_model_fields(self):
        updated_fields = {}
        for field_name in ('organism', 'location', 'selective_marker', 'comments'):
            value = self.cleaned_data.get(field_name)
            if value not in (None, ''):
                updated_fields[field_name] = value

        genotype = self.cleaned_data.get('genotype')
        if genotype:
            updated_fields['genotype'] = genotype.strip()

        plasmids = self.cleaned_data.get('plasmids')
        if plasmids:
            updated_fields['plasmids'] = list(plasmids)

        return updated_fields

    def get_updated_custom_fields(self):
        updates = {}
        for definition in self.custom_field_definitions:
            field_name = self._custom_field_name(definition.id)
            value = self.cleaned_data.get(field_name)
            if value in (None, ''):
                continue
            updates[definition] = value
        return updates


class CSVUploadForm(forms.Form):
    file = forms.FileField(
        label='CSV file',
        help_text='Upload a .csv file to import strains.',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,text/csv'}),
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data['file']
        filename = (uploaded_file.name or '').lower()
        content_type = (uploaded_file.content_type or '').lower()
        valid_types = {'text/csv', 'application/csv', 'application/vnd.ms-excel'}
        if not filename.endswith('.csv') and content_type not in valid_types:
            raise forms.ValidationError('Please upload a valid CSV file.')
        return uploaded_file
