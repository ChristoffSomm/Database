from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from .forms import CustomFieldDefinitionForm, GlobalSearchForm, StrainForm
from .helpers import SESSION_DATABASE_KEY, get_current_database, get_custom_field_definitions, get_custom_field_values
from .models import (
    ActivityLog,
    CustomFieldDefinition,
    DatabaseMembership,
    File,
    Location,
    Organism,
    Plasmid,
    ResearchDatabase,
    Strain,
)
from .permissions import DatabasePermissionMixin

User = get_user_model()


class CurrentDatabaseQuerysetMixin:
    """Filter list/detail querysets to the active research database."""

    def get_current_database(self):
        return getattr(self.request, 'current_database', None) or get_current_database(self.request)

    def get_queryset(self):
        queryset = super().get_queryset()
        current_database = self.get_current_database()
        if current_database is None:
            return queryset.none()
        return queryset.filter(research_database=current_database)


class EditorRequiredMixin(DatabasePermissionMixin):
    required_permission = 'edit'


class MemberManagerRequiredMixin(DatabasePermissionMixin):
    required_permission = 'manage_members'


class DashboardView(LoginRequiredMixin, DatabasePermissionMixin, TemplateView):
    template_name = 'research/dashboard.html'
    required_permission = 'view'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_database = self.get_current_database()
        strains = Strain.objects.filter(research_database=current_database, is_active=True)
        organisms = Organism.objects.filter(research_database=current_database)
        plasmids = Plasmid.objects.filter(research_database=current_database)

        context['strain_count'] = strains.count()
        context['organism_count'] = organisms.count()
        context['plasmid_count'] = plasmids.count()
        context['pending_count'] = strains.filter(status=Strain.Status.PENDING).count()
        context['approved_count'] = strains.filter(status=Strain.Status.APPROVED).count()
        context['archived_count'] = strains.filter(status=Strain.Status.ARCHIVED).count()
        context['recent_organisms'] = organisms.annotate(total=Count('strains')).order_by('-total')[:5]
        context['can_edit'] = current_database.can_edit(self.request.user)
        context['can_manage_members'] = current_database.can_manage_members(self.request.user)
        return context


class SelectDatabaseView(LoginRequiredMixin, TemplateView):
    template_name = 'research/select_database.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['memberships'] = DatabaseMembership.objects.select_related('research_database').filter(user=self.request.user)
        context['current_database_id'] = self.request.session.get(SESSION_DATABASE_KEY)
        return context


class SwitchDatabaseView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        database = get_object_or_404(
            ResearchDatabase,
            id=kwargs.get('database_id') or request.POST.get('database_id'),
            memberships__user=request.user,
        )
        request.session[SESSION_DATABASE_KEY] = database.id
        next_url = request.POST.get('next') or reverse('dashboard')
        return redirect(next_url)


class DatabaseMembersView(LoginRequiredMixin, MemberManagerRequiredMixin, ListView):
    template_name = 'research/membership_list.html'
    context_object_name = 'memberships'

    def get_queryset(self):
        current_database = self.get_current_database()
        return DatabaseMembership.objects.filter(research_database=current_database).select_related('user', 'research_database')

    def post(self, request, *args, **kwargs):
        current_database = self.get_current_database()
        username = (request.POST.get('username') or '').strip()
        role = (request.POST.get('role') or DatabaseMembership.Role.VIEWER).strip()
        valid_roles = {choice[0] for choice in DatabaseMembership.Role.choices}

        if not username:
            messages.error(request, 'Username is required.')
            return HttpResponseRedirect(reverse('membership-list'))

        user = User.objects.filter(username__iexact=username).first()
        if user is None:
            messages.error(request, f'No user found with username "{username}".')
            return HttpResponseRedirect(reverse('membership-list'))

        if role not in valid_roles:
            messages.error(request, 'Invalid role selected.')
            return HttpResponseRedirect(reverse('membership-list'))

        membership, created = DatabaseMembership.objects.get_or_create(
            user=user,
            research_database=current_database,
            defaults={'role': role},
        )
        if created:
            messages.success(request, f'Added {membership.user.username} as {membership.get_role_display()}.')
        else:
            membership.role = role
            membership.save(update_fields=['role'])
            messages.success(request, f'Updated role for {membership.user.username}.')

        return HttpResponseRedirect(reverse('membership-list'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['role_choices'] = DatabaseMembership.Role.choices
        context['is_owner'] = self.get_current_database().is_owner(self.request.user)
        return context


class DatabaseMembershipUpdateRoleView(LoginRequiredMixin, MemberManagerRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        current_database = getattr(request, 'current_database', None) or get_current_database(request)
        membership = get_object_or_404(
            DatabaseMembership,
            id=kwargs['membership_id'],
            research_database=current_database,
        )
        role = request.POST.get('role')
        valid_roles = {choice[0] for choice in DatabaseMembership.Role.choices}

        if role not in valid_roles:
            messages.error(request, 'Invalid role selected.')
            return HttpResponseRedirect(reverse('membership-list'))

        if membership.role == DatabaseMembership.Role.OWNER and not current_database.is_owner(request.user):
            messages.error(request, 'Only the owner can change the owner role.')
            return HttpResponseRedirect(reverse('membership-list'))

        if role == DatabaseMembership.Role.OWNER and not current_database.is_owner(request.user):
            messages.error(request, 'Only the owner can transfer ownership.')
            return HttpResponseRedirect(reverse('membership-list'))

        membership.role = role
        membership.save(update_fields=['role'])
        messages.success(request, f'Updated role for {membership.user.username}.')
        return HttpResponseRedirect(reverse('membership-list'))


class DatabaseMembershipRemoveView(LoginRequiredMixin, MemberManagerRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        current_database = getattr(request, 'current_database', None) or get_current_database(request)
        membership = get_object_or_404(
            DatabaseMembership,
            id=kwargs['membership_id'],
            research_database=current_database,
        )

        if membership.role == DatabaseMembership.Role.OWNER:
            messages.error(request, 'Owner cannot be removed from the database.')
            return HttpResponseRedirect(reverse('membership-list'))

        username = membership.user.username
        membership.delete()
        messages.success(request, f'Removed {username} from this database.')
        return HttpResponseRedirect(reverse('membership-list'))


class DatabaseTransferOwnershipView(LoginRequiredMixin, DatabasePermissionMixin, View):
    required_permission = 'owner'

    def post(self, request, *args, **kwargs):
        current_database = getattr(request, 'current_database', None) or get_current_database(request)
        new_owner = get_object_or_404(
            DatabaseMembership,
            id=kwargs['membership_id'],
            research_database=current_database,
        )
        current_owner = current_database.memberships.filter(role=DatabaseMembership.Role.OWNER).first()

        if current_owner and current_owner.id == new_owner.id:
            messages.info(request, f'{new_owner.user.username} is already the owner.')
            return HttpResponseRedirect(reverse('membership-list'))

        if current_owner:
            current_owner.role = DatabaseMembership.Role.ADMIN
            current_owner.save(update_fields=['role'])

        new_owner.role = DatabaseMembership.Role.OWNER
        new_owner.save(update_fields=['role'])
        messages.success(request, f'{new_owner.user.username} is now the database owner.')
        return HttpResponseRedirect(reverse('membership-list'))


class CustomFieldDefinitionListView(LoginRequiredMixin, EditorRequiredMixin, ListView):
    model = CustomFieldDefinition
    template_name = 'research/custom_field_definition_list.html'
    context_object_name = 'custom_field_definitions'

    def get_queryset(self):
        current_database = getattr(self.request, 'current_database', None) or get_current_database(self.request)
        return CustomFieldDefinition.objects.filter(research_database=current_database).order_by('name')


class CustomFieldDefinitionCreateView(LoginRequiredMixin, EditorRequiredMixin, CreateView):
    model = CustomFieldDefinition
    form_class = CustomFieldDefinitionForm
    template_name = 'research/custom_field_definition_form.html'
    success_url = reverse_lazy('custom-field-definition-list')

    def form_valid(self, form):
        current_database = getattr(self.request, 'current_database', None) or get_current_database(self.request)
        form.instance.research_database = current_database
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Custom field "{form.instance.name}" created.')
        return super().form_valid(form)


class CustomFieldDefinitionUpdateView(LoginRequiredMixin, EditorRequiredMixin, UpdateView):
    model = CustomFieldDefinition
    form_class = CustomFieldDefinitionForm
    template_name = 'research/custom_field_definition_form.html'
    success_url = reverse_lazy('custom-field-definition-list')

    def get_queryset(self):
        current_database = getattr(self.request, 'current_database', None) or get_current_database(self.request)
        return CustomFieldDefinition.objects.filter(research_database=current_database)


class CustomFieldDefinitionDeleteView(LoginRequiredMixin, EditorRequiredMixin, DeleteView):
    model = CustomFieldDefinition
    template_name = 'research/custom_field_definition_confirm_delete.html'
    success_url = reverse_lazy('custom-field-definition-list')

    def get_queryset(self):
        current_database = getattr(self.request, 'current_database', None) or get_current_database(self.request)
        return CustomFieldDefinition.objects.filter(research_database=current_database)


class StrainListView(LoginRequiredMixin, DatabasePermissionMixin, CurrentDatabaseQuerysetMixin, ListView):
    model = Strain
    template_name = 'research/strain_list.html'
    context_object_name = 'strains'
    paginate_by = 25
    required_permission = 'view'

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(is_active=True)
            .select_related('organism', 'location')
            .prefetch_related('plasmids')
        )

        search_query = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()
        organism_id = self.request.GET.get('organism', '').strip()

        if search_query:
            queryset = queryset.filter(
                Q(strain_id__icontains=search_query)
                | Q(name__icontains=search_query)
                | Q(custom_field_values__value_text__icontains=search_query)
                | Q(custom_field_values__value_choice__icontains=search_query)
            )
        if status:
            queryset = queryset.filter(status=status)
        if organism_id:
            queryset = queryset.filter(organism_id=organism_id)

        for definition in get_custom_field_definitions(self.get_current_database()):
            field_key = f'cf_{definition.id}'
            raw_value = self.request.GET.get(field_key, '').strip()
            if raw_value == '':
                continue

            if definition.field_type == CustomFieldDefinition.FieldType.TEXT:
                queryset = queryset.filter(
                    custom_field_values__field_definition=definition,
                    custom_field_values__value_text__icontains=raw_value,
                )
            elif definition.field_type == CustomFieldDefinition.FieldType.NUMBER:
                try:
                    queryset = queryset.filter(
                        custom_field_values__field_definition=definition,
                        custom_field_values__value_number=float(raw_value),
                    )
                except ValueError:
                    continue
            elif definition.field_type == CustomFieldDefinition.FieldType.DATE:
                queryset = queryset.filter(
                    custom_field_values__field_definition=definition,
                    custom_field_values__value_date=raw_value,
                )
            elif definition.field_type == CustomFieldDefinition.FieldType.BOOLEAN:
                queryset = queryset.filter(
                    custom_field_values__field_definition=definition,
                    custom_field_values__value_boolean=raw_value.lower() in {'true', '1', 'yes'},
                )
            elif definition.field_type == CustomFieldDefinition.FieldType.CHOICE:
                queryset = queryset.filter(
                    custom_field_values__field_definition=definition,
                    custom_field_values__value_choice=raw_value,
                )

        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_database = self.get_current_database()
        definitions = list(get_custom_field_definitions(current_database))
        context['search_query'] = self.request.GET.get('q', '').strip()
        context['selected_status'] = self.request.GET.get('status', '').strip()
        context['selected_organism'] = self.request.GET.get('organism', '').strip()
        context['status_choices'] = Strain.Status.choices
        context['organisms'] = Organism.objects.filter(research_database=current_database).order_by('name')
        context['custom_field_filters'] = [
            {
                'id': definition.id,
                'name': definition.name,
                'field_type': definition.field_type,
                'options': definition.parsed_choices(),
                'selected_value': self.request.GET.get(f'cf_{definition.id}', '').strip(),
            }
            for definition in definitions
        ]
        return context


class StrainDetailView(LoginRequiredMixin, DatabasePermissionMixin, CurrentDatabaseQuerysetMixin, DetailView):
    model = Strain
    template_name = 'research/strain_detail.html'
    context_object_name = 'strain'
    required_permission = 'view'

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(is_active=True)
            .select_related('organism', 'location', 'created_by')
            .prefetch_related('plasmids', 'files')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        strain = context['strain']
        context['history'] = ActivityLog.objects.filter(
            model_name='Strain',
            object_id=str(strain.pk),
            research_database=strain.research_database,
        )[:20]
        context['custom_field_values'] = get_custom_field_values(strain)
        return context


class StrainCreateView(LoginRequiredMixin, EditorRequiredMixin, CreateView):
    model = Strain
    form_class = StrainForm
    template_name = 'research/strain_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f'Strain {self.object.strain_id} created successfully.')
        return response


class StrainUpdateView(LoginRequiredMixin, EditorRequiredMixin, CurrentDatabaseQuerysetMixin, UpdateView):
    model = Strain
    form_class = StrainForm
    template_name = 'research/strain_form.html'

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Strain {self.object.strain_id} updated successfully.')
        return response


class StrainDeleteView(LoginRequiredMixin, EditorRequiredMixin, CurrentDatabaseQuerysetMixin, DeleteView):
    model = Strain
    template_name = 'research/strain_confirm_delete.html'
    success_url = reverse_lazy('strain-list')

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)

    def form_valid(self, form):
        self.object = self.get_object()
        self.object.is_active = False
        self.object.save(update_fields=['is_active', 'updated_at'])
        messages.success(self.request, f'Strain {self.object.strain_id} deleted successfully.')
        return HttpResponseRedirect(self.get_success_url())


class OrganismDetailView(LoginRequiredMixin, CurrentDatabaseQuerysetMixin, DetailView):
    model = Organism
    template_name = 'research/organism_detail.html'
    context_object_name = 'organism'


class PlasmidDetailView(LoginRequiredMixin, CurrentDatabaseQuerysetMixin, DetailView):
    model = Plasmid
    template_name = 'research/plasmid_detail.html'
    context_object_name = 'plasmid'


class LocationDetailView(LoginRequiredMixin, CurrentDatabaseQuerysetMixin, DetailView):
    model = Location
    template_name = 'research/location_detail.html'
    context_object_name = 'location'


class FileDetailView(LoginRequiredMixin, CurrentDatabaseQuerysetMixin, DetailView):
    model = File
    template_name = 'research/file_detail.html'
    context_object_name = 'file_obj'


class SearchResultsView(LoginRequiredMixin, DatabasePermissionMixin, TemplateView):
    template_name = 'research/search_results.html'
    required_permission = 'view'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = GlobalSearchForm(self.request.GET or None)
        context['form'] = form
        context['query'] = ''

        grouped_results = {
            'strains': [],
            'organisms': [],
            'plasmids': [],
            'locations': [],
            'files': [],
        }

        if form.is_valid():
            query = form.cleaned_data.get('q', '')
            context['query'] = query
            if query:
                current_database = self.request.current_database
                grouped_results['strains'] = list(
                    Strain.objects.filter(research_database=current_database, is_active=True)
                    .filter(
                        Q(strain_id__icontains=query)
                        | Q(name__icontains=query)
                        | Q(custom_field_values__value_text__icontains=query)
                        | Q(custom_field_values__value_choice__icontains=query)
                    )
                    .distinct()[:50]
                )
                grouped_results['organisms'] = list(
                    Organism.objects.filter(research_database=current_database, name__icontains=query)[:50]
                )
                grouped_results['plasmids'] = list(
                    Plasmid.objects.filter(research_database=current_database, name__icontains=query)[:50]
                )
                grouped_results['locations'] = list(
                    Location.objects.filter(research_database=current_database).filter(
                        Q(building__icontains=query)
                        | Q(freezer__icontains=query)
                        | Q(box__icontains=query)
                        | Q(position__icontains=query)
                    )[:50]
                )
                grouped_results['files'] = list(
                    File.objects.filter(research_database=current_database, file__icontains=query)
                    .select_related('strain')[:50]
                )

        context['grouped_results'] = grouped_results
        context['result_counts'] = {key: len(values) for key, values in grouped_results.items()}
        context['total_results'] = sum(context['result_counts'].values())
        return context


class ActivityFeedView(LoginRequiredMixin, DatabasePermissionMixin, ListView):
    template_name = 'research/activity_feed.html'
    context_object_name = 'activity_logs'
    paginate_by = 25
    required_permission = 'view'

    def get_queryset(self):
        current_database = getattr(self.request, 'current_database', None) or get_current_database(self.request)
        queryset = ActivityLog.objects.filter(research_database=current_database).select_related('user', 'research_database')

        user_id = self.request.GET.get('user', '').strip()
        model_name = self.request.GET.get('model_name', '').strip()
        action = self.request.GET.get('action', '').strip()
        start_date = self.request.GET.get('start_date', '').strip()
        end_date = self.request.GET.get('end_date', '').strip()

        if user_id:
            queryset = queryset.filter(user_id=user_id)
        if model_name:
            queryset = queryset.filter(model_name__iexact=model_name)
        if action:
            queryset = queryset.filter(action=action)
        if start_date:
            queryset = queryset.filter(timestamp__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__date__lte=end_date)

        return queryset.order_by('-timestamp')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_database = getattr(self.request, 'current_database', None) or get_current_database(self.request)
        context['selected_user'] = self.request.GET.get('user', '').strip()
        context['selected_model_name'] = self.request.GET.get('model_name', '').strip()
        context['selected_action'] = self.request.GET.get('action', '').strip()
        context['selected_start_date'] = self.request.GET.get('start_date', '').strip()
        context['selected_end_date'] = self.request.GET.get('end_date', '').strip()
        context['users'] = (
            DatabaseMembership.objects.filter(research_database=current_database)
            .select_related('user')
            .order_by('user__username')
        )
        context['actions'] = ActivityLog.Action.choices
        context['model_names'] = (
            ActivityLog.objects.filter(research_database=current_database)
            .order_by('model_name')
            .values_list('model_name', flat=True)
            .distinct()
        )
        return context
