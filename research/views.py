from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from .forms import CustomFieldDefinitionForm, GlobalSearchForm, SavedViewForm, StrainForm
from .filtering import apply_filters
from .helpers import SESSION_DATABASE_KEY, get_active_database, get_custom_field_definitions, get_custom_field_values
from .models import (
    ActivityLog,
    CustomFieldDefinition,
    DatabaseMembership,
    File,
    Location,
    Organism,
    Plasmid,
    ResearchDatabase,
    SavedView,
    Strain,
)
from .permissions import DatabasePermissionMixin

User = get_user_model()


class CurrentDatabaseQuerysetMixin:
    """Filter list/detail querysets to the active research database."""

    def get_active_database(self):
        return getattr(self.request, 'active_database', None) or get_active_database(self.request)

    def get_queryset(self):
        queryset = super().get_queryset()
        active_database = self.get_active_database()
        if active_database is None:
            return queryset.none()
        return queryset.filter(research_database=active_database)


class EditorRequiredMixin(DatabasePermissionMixin):
    required_permission = 'edit'


class MemberManagerRequiredMixin(DatabasePermissionMixin):
    required_permission = 'manage_members'


class DashboardView(LoginRequiredMixin, DatabasePermissionMixin, TemplateView):
    template_name = 'research/dashboard.html'
    required_permission = 'view'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_database = self.get_active_database()
        strains = Strain.objects.filter(research_database=active_database, is_active=True)
        organisms = Organism.objects.filter(research_database=active_database)
        plasmids = Plasmid.objects.filter(research_database=active_database)

        context['strain_count'] = strains.count()
        context['organism_count'] = organisms.count()
        context['plasmid_count'] = plasmids.count()
        context['pending_count'] = strains.filter(status=Strain.Status.PENDING).count()
        context['approved_count'] = strains.filter(status=Strain.Status.APPROVED).count()
        context['archived_count'] = strains.filter(status=Strain.Status.ARCHIVED).count()
        context['recent_organisms'] = organisms.annotate(total=Count('strains')).order_by('-total')[:5]
        context['can_edit'] = active_database.can_edit(self.request.user)
        context['can_manage_members'] = active_database.can_manage_members(self.request.user)
        context['saved_views'] = SavedView.objects.filter(research_database=active_database).filter(
            Q(is_shared=True) | Q(created_by=self.request.user)
        ).select_related('created_by').order_by('name')
        return context


class CreateDatabaseView(LoginRequiredMixin, CreateView):
    model = ResearchDatabase
    template_name = 'research/database_form.html'
    fields = ['name', 'description']

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        self.request.session[SESSION_DATABASE_KEY] = self.object.id
        messages.success(self.request, f'Database "{self.object.name}" created successfully.')
        return response

    def get_success_url(self):
        return reverse('dashboard')


class SelectDatabaseView(LoginRequiredMixin, TemplateView):
    template_name = 'research/select_database.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['memberships'] = DatabaseMembership.objects.select_related('research_database').filter(user=self.request.user)
        context['active_database_id'] = self.request.session.get(SESSION_DATABASE_KEY)
        return context


@login_required
def switch_database(request, database_id):
    database = get_object_or_404(
        ResearchDatabase,
        id=database_id,
        memberships__user=request.user,
    )
    request.session[SESSION_DATABASE_KEY] = database.id
    next_url = request.META.get('HTTP_REFERER') or reverse('dashboard')
    return redirect(next_url)


class SwitchDatabaseView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        database_id = kwargs.get('database_id') or request.POST.get('database_id')
        if not database_id:
            return redirect(reverse('dashboard'))
        return switch_database(request, database_id=int(database_id))


class DatabaseMembersView(LoginRequiredMixin, MemberManagerRequiredMixin, ListView):
    template_name = 'research/membership_list.html'
    context_object_name = 'memberships'

    def get_queryset(self):
        active_database = self.get_active_database()
        return DatabaseMembership.objects.filter(research_database=active_database).select_related('user', 'research_database')

    def post(self, request, *args, **kwargs):
        active_database = self.get_active_database()
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
            research_database=active_database,
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
        context['is_owner'] = self.get_active_database().is_owner(self.request.user)
        return context


class DatabaseMembershipUpdateRoleView(LoginRequiredMixin, MemberManagerRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        active_database = getattr(request, 'active_database', None) or get_active_database(request)
        membership = get_object_or_404(
            DatabaseMembership,
            id=kwargs['membership_id'],
            research_database=active_database,
        )
        role = request.POST.get('role')
        valid_roles = {choice[0] for choice in DatabaseMembership.Role.choices}

        if role not in valid_roles:
            messages.error(request, 'Invalid role selected.')
            return HttpResponseRedirect(reverse('membership-list'))

        if membership.role == DatabaseMembership.Role.OWNER and not active_database.is_owner(request.user):
            messages.error(request, 'Only the owner can change the owner role.')
            return HttpResponseRedirect(reverse('membership-list'))

        if role == DatabaseMembership.Role.OWNER and not active_database.is_owner(request.user):
            messages.error(request, 'Only the owner can transfer ownership.')
            return HttpResponseRedirect(reverse('membership-list'))

        membership.role = role
        membership.save(update_fields=['role'])
        messages.success(request, f'Updated role for {membership.user.username}.')
        return HttpResponseRedirect(reverse('membership-list'))


class DatabaseMembershipRemoveView(LoginRequiredMixin, MemberManagerRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        active_database = getattr(request, 'active_database', None) or get_active_database(request)
        membership = get_object_or_404(
            DatabaseMembership,
            id=kwargs['membership_id'],
            research_database=active_database,
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
        active_database = getattr(request, 'active_database', None) or get_active_database(request)
        new_owner = get_object_or_404(
            DatabaseMembership,
            id=kwargs['membership_id'],
            research_database=active_database,
        )
        current_owner = active_database.memberships.filter(role=DatabaseMembership.Role.OWNER).first()

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
        active_database = getattr(self.request, 'active_database', None) or get_active_database(self.request)
        return CustomFieldDefinition.objects.filter(research_database=active_database).order_by('name')


class CustomFieldDefinitionCreateView(LoginRequiredMixin, EditorRequiredMixin, CreateView):
    model = CustomFieldDefinition
    form_class = CustomFieldDefinitionForm
    template_name = 'research/custom_field_definition_form.html'
    success_url = reverse_lazy('custom-field-definition-list')

    def form_valid(self, form):
        active_database = getattr(self.request, 'active_database', None) or get_active_database(self.request)
        form.instance.research_database = active_database
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Custom field "{form.instance.name}" created.')
        return super().form_valid(form)


class CustomFieldDefinitionUpdateView(LoginRequiredMixin, EditorRequiredMixin, UpdateView):
    model = CustomFieldDefinition
    form_class = CustomFieldDefinitionForm
    template_name = 'research/custom_field_definition_form.html'
    success_url = reverse_lazy('custom-field-definition-list')

    def get_queryset(self):
        active_database = getattr(self.request, 'active_database', None) or get_active_database(self.request)
        return CustomFieldDefinition.objects.filter(research_database=active_database)


class CustomFieldDefinitionDeleteView(LoginRequiredMixin, EditorRequiredMixin, DeleteView):
    model = CustomFieldDefinition
    template_name = 'research/custom_field_definition_confirm_delete.html'
    success_url = reverse_lazy('custom-field-definition-list')

    def get_queryset(self):
        active_database = getattr(self.request, 'active_database', None) or get_active_database(self.request)
        return CustomFieldDefinition.objects.filter(research_database=active_database)


def _saved_view_queryset_for_user(database, user):
    return SavedView.objects.filter(research_database=database).filter(Q(is_shared=True) | Q(created_by=user))


class CreateSavedViewView(LoginRequiredMixin, DatabasePermissionMixin, View):
    required_permission = 'view'

    def post(self, request, *args, **kwargs):
        active_database = self.get_active_database()
        form = SavedViewForm(request.POST)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return HttpResponseRedirect(reverse('dashboard'))

        filter_definition_raw = request.POST.get('filter_definition', '{}')
        import json

        try:
            filter_definition = json.loads(filter_definition_raw)
        except json.JSONDecodeError:
            return HttpResponseBadRequest('Invalid filter definition.')

        saved_view = form.save(commit=False)
        saved_view.research_database = active_database
        saved_view.created_by = request.user
        saved_view.filter_definition = filter_definition
        saved_view.save()
        messages.success(request, f'Saved view "{saved_view.name}" created.')
        return HttpResponseRedirect(reverse('dashboard'))


class UpdateSavedViewView(LoginRequiredMixin, DatabasePermissionMixin, View):
    required_permission = 'view'

    def post(self, request, *args, **kwargs):
        active_database = self.get_active_database()
        saved_view = get_object_or_404(_saved_view_queryset_for_user(active_database, request.user), pk=kwargs['pk'])
        if saved_view.created_by_id != request.user.id and not active_database.can_manage_members(request.user):
            return HttpResponseBadRequest('You cannot update this saved view.')

        form = SavedViewForm(request.POST, instance=saved_view)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return HttpResponseRedirect(reverse('dashboard'))

        filter_definition_raw = request.POST.get('filter_definition', '{}')
        import json

        try:
            filter_definition = json.loads(filter_definition_raw)
        except json.JSONDecodeError:
            return HttpResponseBadRequest('Invalid filter definition.')

        updated = form.save(commit=False)
        updated.filter_definition = filter_definition
        updated.save()
        messages.success(request, f'Saved view "{updated.name}" updated.')
        return HttpResponseRedirect(reverse('dashboard'))


class DeleteSavedViewView(LoginRequiredMixin, DatabasePermissionMixin, View):
    required_permission = 'view'

    def post(self, request, *args, **kwargs):
        active_database = self.get_active_database()
        saved_view = get_object_or_404(_saved_view_queryset_for_user(active_database, request.user), pk=kwargs['pk'])

        can_delete = saved_view.created_by_id == request.user.id
        if saved_view.is_shared:
            can_delete = can_delete or active_database.can_manage_members(request.user)

        if not can_delete:
            return HttpResponseBadRequest('You do not have permission to delete this view.')

        view_name = saved_view.name
        saved_view.delete()
        messages.success(request, f'Saved view "{view_name}" deleted.')
        return HttpResponseRedirect(reverse('dashboard'))


class ApplySavedViewView(LoginRequiredMixin, DatabasePermissionMixin, View):
    required_permission = 'view'

    def get(self, request, *args, **kwargs):
        active_database = self.get_active_database()
        saved_view = get_object_or_404(_saved_view_queryset_for_user(active_database, request.user), pk=kwargs['pk'])
        return redirect(f"{reverse('strain-list')}?saved_view={saved_view.pk}")



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

        for definition in get_custom_field_definitions(self.get_active_database()):
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

        saved_view_id = self.request.GET.get('saved_view', '').strip()
        if saved_view_id:
            saved_view = _saved_view_queryset_for_user(self.get_active_database(), self.request.user).filter(pk=saved_view_id).first()
            if saved_view:
                queryset = apply_filters(queryset, saved_view.filter_definition)

        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_database = self.get_active_database()
        definitions = list(get_custom_field_definitions(active_database))
        context['search_query'] = self.request.GET.get('q', '').strip()
        context['selected_status'] = self.request.GET.get('status', '').strip()
        context['selected_organism'] = self.request.GET.get('organism', '').strip()
        context['status_choices'] = Strain.Status.choices
        context['organisms'] = Organism.objects.filter(research_database=active_database).order_by('name')
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
        context['saved_views'] = _saved_view_queryset_for_user(active_database, self.request.user).select_related('created_by').order_by('name')
        context['active_saved_view'] = self.request.GET.get('saved_view', '').strip()
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
                active_database = self.request.active_database
                grouped_results['strains'] = list(
                    Strain.objects.filter(research_database=active_database, is_active=True)
                    .filter(
                        Q(strain_id__icontains=query)
                        | Q(name__icontains=query)
                        | Q(custom_field_values__value_text__icontains=query)
                        | Q(custom_field_values__value_choice__icontains=query)
                    )
                    .distinct()[:50]
                )
                grouped_results['organisms'] = list(
                    Organism.objects.filter(research_database=active_database, name__icontains=query)[:50]
                )
                grouped_results['plasmids'] = list(
                    Plasmid.objects.filter(research_database=active_database, name__icontains=query)[:50]
                )
                grouped_results['locations'] = list(
                    Location.objects.filter(research_database=active_database).filter(
                        Q(building__icontains=query)
                        | Q(freezer__icontains=query)
                        | Q(box__icontains=query)
                        | Q(position__icontains=query)
                    )[:50]
                )
                grouped_results['files'] = list(
                    File.objects.filter(research_database=active_database, file__icontains=query)
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
        active_database = getattr(self.request, 'active_database', None) or get_active_database(self.request)
        queryset = ActivityLog.objects.filter(research_database=active_database).select_related('user', 'research_database')

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
        active_database = getattr(self.request, 'active_database', None) or get_active_database(self.request)
        context['selected_user'] = self.request.GET.get('user', '').strip()
        context['selected_model_name'] = self.request.GET.get('model_name', '').strip()
        context['selected_action'] = self.request.GET.get('action', '').strip()
        context['selected_start_date'] = self.request.GET.get('start_date', '').strip()
        context['selected_end_date'] = self.request.GET.get('end_date', '').strip()
        context['users'] = (
            DatabaseMembership.objects.filter(research_database=active_database)
            .select_related('user')
            .order_by('user__username')
        )
        context['actions'] = ActivityLog.Action.choices
        context['model_names'] = (
            ActivityLog.objects.filter(research_database=active_database)
            .order_by('model_name')
            .values_list('model_name', flat=True)
            .distinct()
        )
        return context
