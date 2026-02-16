from django import forms

from .helpers import get_current_database
from .models import Location, Organism, Plasmid, Strain


class GlobalSearchForm(forms.Form):
    q = forms.CharField(max_length=200, required=False, strip=True)


class StrainForm(forms.ModelForm):
    class Meta:
        model = Strain
        fields = ['strain_id', 'name', 'organism', 'genotype', 'plasmids', 'location', 'status']
        widgets = {
            'genotype': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

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

    def _get_current_database(self):
        if not self.request:
            return None
        return getattr(self.request, 'current_database', None) or get_current_database(self.request)

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
        return instance
