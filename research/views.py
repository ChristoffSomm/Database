from datetime import date
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from .forms import (
    BulkEditStrainsForm,
    CSVUploadForm,
    CustomFieldDefinitionForm,
    GlobalSearchForm,
    SavedViewForm,
    StrainAttachmentUploadForm,
    StrainForm,
)
from .filtering import apply_filters
from .helpers import SESSION_DATABASE_KEY, get_active_database, get_custom_field_definitions, get_custom_field_values
from .import_utils import (
    STANDARD_IMPORT_FIELDS,
    build_mapped_rows,
    import_strains_from_csv_rows,
    parse_csv_upload,
    validate_import_row,
)
from .models import (
    ActivityLog,
    AuditLog,
    CustomFieldDefinition,
    CustomFieldValue,
    DatabaseMembership,
    File,
    Location,
    Organism,
    Plasmid,
    ResearchDatabase,
    SavedView,
    Strain,
    StrainAttachment,
    StrainVersion,
)
from .permissions import DatabasePermissionMixin
from .versioning import compare_versions, serialize_strain_snapshot

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


def _can_delete_attachments(database, user):
    role = database.get_user_role(user)
    return role in {DatabaseMembership.Role.OWNER, DatabaseMembership.Role.ADMIN}


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

        include_archived = self.request.GET.get('include_archived', '').strip().lower() in {'1', 'true', 'yes'}
        if not include_archived:
            queryset = queryset.filter(is_archived=False)

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
        context['can_bulk_edit'] = active_database.can_edit(self.request.user)
        return context


class BulkEditStrainsView(LoginRequiredMixin, EditorRequiredMixin, CurrentDatabaseQuerysetMixin, TemplateView):
    template_name = 'research/strain_bulk_edit.html'

    def _selected_ids(self):
        ids = self.request.POST.getlist('strain_ids')
        return [int(pk) for pk in ids if str(pk).isdigit()]

    def _selected_queryset(self):
        active_database = self.get_active_database()
        return Strain.objects.filter(
            research_database=active_database,
            is_active=True,
            id__in=self._selected_ids(),
        )

    def post(self, request, *args, **kwargs):
        active_database = self.get_active_database()
        selected_strains = self._selected_queryset().select_related('organism', 'location').prefetch_related('plasmids')

        if not selected_strains.exists():
            messages.error(request, 'Please select at least one valid strain.')
            return HttpResponseRedirect(reverse('strain-list'))

        requested_count = len(self._selected_ids())
        if selected_strains.count() != requested_count:
            return HttpResponseBadRequest('Invalid strain selection for active database.')

        action = (request.POST.get('bulk_action') or 'edit').strip()
        if action == 'delete':
            if not (active_database.is_owner(request.user) or active_database.get_user_role(request.user) == DatabaseMembership.Role.ADMIN):
                return HttpResponseBadRequest('Only database owners/admins can bulk delete.')
            count = selected_strains.update(is_active=False)
            AuditLog.objects.create(
                user=request.user,
                action='bulk_delete',
                record_type='Strain',
                record_id=','.join(str(sid) for sid in selected_strains.values_list('id', flat=True)),
            )
            messages.success(request, f'{count} strains deleted successfully.')
            return HttpResponseRedirect(reverse('strain-list'))

        if action == 'archive':
            count = selected_strains.update(is_archived=True)
            AuditLog.objects.create(
                user=request.user,
                action='bulk_archive',
                record_type='Strain',
                record_id=','.join(str(sid) for sid in selected_strains.values_list('id', flat=True)),
            )
            messages.success(request, f'{count} strains archived successfully.')
            return HttpResponseRedirect(reverse('strain-list'))

        form = BulkEditStrainsForm(request.POST or None, request=request)
        if request.POST.get('apply_bulk_edit') == '1':
            if form.is_valid():
                updated_fields = form.get_updated_model_fields()
                updated_custom_fields = form.get_updated_custom_fields()

                if not updated_fields and not updated_custom_fields:
                    messages.error(request, 'Provide at least one field to update.')
                    return self.render_to_response(self.get_context_data(form=form, selected_strains=selected_strains))

                with transaction.atomic():
                    for strain in selected_strains:
                        update_fields = []
                        for field_name, value in updated_fields.items():
                            if field_name == 'plasmids':
                                strain.plasmids.set(value)
                                continue
                            setattr(strain, field_name, value)
                            update_fields.append(field_name)

                        if update_fields:
                            update_fields.append('updated_at')
                            strain.save(update_fields=update_fields)

                        for definition, value in updated_custom_fields.items():
                            custom_value, _ = CustomFieldValue.objects.get_or_create(strain=strain, field_definition=definition)
                            custom_value.value_text = None
                            custom_value.value_number = None
                            custom_value.value_date = None
                            custom_value.value_boolean = None
                            custom_value.value_choice = None

                            if definition.field_type == CustomFieldDefinition.FieldType.TEXT:
                                custom_value.value_text = value.strip() if isinstance(value, str) else value
                            elif definition.field_type == CustomFieldDefinition.FieldType.NUMBER:
                                custom_value.value_number = value
                            elif definition.field_type == CustomFieldDefinition.FieldType.DATE:
                                custom_value.value_date = value
                            elif definition.field_type == CustomFieldDefinition.FieldType.BOOLEAN:
                                custom_value.value_boolean = value
                            elif definition.field_type == CustomFieldDefinition.FieldType.CHOICE:
                                custom_value.value_choice = value
                            custom_value.save()

                updated_field_names = list(updated_fields.keys()) + [f'custom:{d.name}' for d in updated_custom_fields.keys()]
                AuditLog.objects.create(
                    user=request.user,
                    action='bulk_update',
                    record_type='Strain',
                    record_id=','.join(str(sid) for sid in selected_strains.values_list('id', flat=True)),
                )
                ActivityLog.objects.create(
                    research_database=active_database,
                    user=request.user,
                    model_name='Strain',
                    object_id='bulk',
                    action=ActivityLog.Action.UPDATE,
                    changes={'fields': updated_field_names, 'count': selected_strains.count()},
                    summary=f'Bulk updated {selected_strains.count()} strains. Fields: {", ".join(updated_field_names)}',
                )
                messages.success(request, f'Updated {selected_strains.count()} strains successfully.')
                return HttpResponseRedirect(reverse('strain-list'))
        else:
            form = BulkEditStrainsForm(request=request)

        return self.render_to_response(self.get_context_data(form=form, selected_strains=selected_strains))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('form', BulkEditStrainsForm(request=self.request))
        selected_strains = kwargs.get('selected_strains')
        if selected_strains is None:
            selected_strains = self._selected_queryset()
        context['selected_strains'] = selected_strains
        context['selected_count'] = selected_strains.count()
        context['selected_ids'] = [strain.id for strain in selected_strains]
        return context


class CSVUploadView(LoginRequiredMixin, EditorRequiredMixin, TemplateView):
    template_name = 'research/csv_upload.html'

    session_key = 'csv_import_state'

    def _get_state(self):
        return self.request.session.get(self.session_key, {})

    def _set_state(self, **kwargs):
        state = self._get_state()
        state.update(kwargs)
        self.request.session[self.session_key] = state
        self.request.session.modified = True

    def _clear_state(self):
        self.request.session.pop(self.session_key, None)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        state = self._get_state()
        active_database = self.get_active_database()
        custom_fields = list(get_custom_field_definitions(active_database))
        mapping_choices = [('', 'Do not import')]
        mapping_choices.extend(STANDARD_IMPORT_FIELDS)
        mapping_choices.extend([(f'custom:{field.name}', f'Custom: {field.name}') for field in custom_fields])

        context.update(
            {
                'form': kwargs.get('form') or CSVUploadForm(),
                'step': kwargs.get('step') or state.get('step', 'upload'),
                'headers': state.get('headers', []),
                'header_mappings': [
                    {'header': header, 'selected': state.get('column_mapping', {}).get(header, '')}
                    for header in state.get('headers', [])
                ],
                'filename': state.get('filename', ''),
                'column_mapping': state.get('column_mapping', {}),
                'mapping_choices': mapping_choices,
                'preview_entries': kwargs.get('preview_entries', []),
                'mapped_field_names': kwargs.get('mapped_field_names', []),
            }
        )
        return context

    def get(self, request, *args, **kwargs):
        state = self._get_state()
        step = request.GET.get('step') or state.get('step') or 'upload'
        if step not in {'upload', 'mapping', 'preview'}:
            step = 'upload'

        if step == 'mapping' and not state.get('headers'):
            step = 'upload'
        if step == 'preview' and not state.get('column_mapping'):
            step = 'mapping' if state.get('headers') else 'upload'

        if step == 'preview':
            preview_entries, mapped_field_names = self._build_preview(state)
            return self.render_to_response(
                self.get_context_data(
                    step='preview',
                    preview_entries=preview_entries,
                    mapped_field_names=mapped_field_names,
                )
            )

        return self.render_to_response(self.get_context_data(step=step))

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', 'upload')
        if action == 'cancel':
            self._clear_state()
            messages.info(request, 'CSV import cancelled.')
            return HttpResponseRedirect(reverse('csv_upload'))

        if action == 'upload':
            form = CSVUploadForm(request.POST, request.FILES)
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(step='upload', form=form))

            uploaded_file = form.cleaned_data['file']
            try:
                headers, rows = parse_csv_upload(uploaded_file)
            except Exception as exc:  # noqa: BLE001
                form.add_error('file', str(exc))
                return self.render_to_response(self.get_context_data(step='upload', form=form))

            self._set_state(step='mapping', filename=uploaded_file.name, headers=headers, rows=rows, column_mapping={})
            messages.success(request, 'CSV uploaded successfully. Map your columns to strain fields.')
            return HttpResponseRedirect(f"{reverse('csv_upload')}?step=mapping")

        state = self._get_state()
        if not state.get('headers'):
            messages.error(request, 'Upload a CSV file first.')
            return HttpResponseRedirect(reverse('csv_upload'))

        if action == 'mapping':
            column_mapping = {}
            used_fields = set()
            mapping_error = False
            for header in state.get('headers', []):
                mapped_field = (request.POST.get(f'map_{header}') or '').strip()
                column_mapping[header] = mapped_field
                if not mapped_field:
                    continue
                if mapped_field in used_fields:
                    mapping_error = True
                used_fields.add(mapped_field)

            if mapping_error:
                messages.error(request, 'Each target field can only be mapped once.')
                self._set_state(step='mapping', column_mapping=column_mapping)
                return self.render_to_response(self.get_context_data(step='mapping'))

            self._set_state(step='preview', column_mapping=column_mapping)
            return HttpResponseRedirect(f"{reverse('csv_upload')}?step=preview")

        if action == 'confirm_import':
            active_database = self.get_active_database()
            custom_definitions = {definition.name: definition for definition in get_custom_field_definitions(active_database)}
            mapped_rows = build_mapped_rows(state.get('rows', []), state.get('column_mapping', {}))
            created_count, skipped_count = import_strains_from_csv_rows(
                active_database=active_database,
                user=request.user,
                mapped_rows=mapped_rows,
                custom_definitions_by_name=custom_definitions,
            )

            AuditLog.objects.create(
                user=request.user,
                action='csv_import',
                record_type='Strain',
                record_id=str(active_database.id),
                metadata={
                    'rows_created': created_count,
                    'rows_skipped': skipped_count,
                    'filename': state.get('filename', ''),
                },
            )

            self._clear_state()
            messages.success(request, f'Import complete. Created: {created_count}. Skipped: {skipped_count}.')
            return HttpResponseRedirect(reverse('strain-list'))

        messages.error(request, 'Unknown CSV import action.')
        return HttpResponseRedirect(reverse('csv_upload'))

    def _build_preview(self, state):
        active_database = self.get_active_database()
        custom_definitions = {definition.name: definition for definition in get_custom_field_definitions(active_database)}
        mapped_rows = build_mapped_rows(state.get('rows', []), state.get('column_mapping', {}))
        mapped_field_names = [value for value in state.get('column_mapping', {}).values() if value]

        preview_entries = []
        for index, mapped_row in enumerate(mapped_rows[:10]):
            row_errors = validate_import_row(mapped_row, active_database, custom_definitions)
            preview_entries.append(
                {
                    'row_number': index + 1,
                    'cells': [mapped_row.get(field_name, '') for field_name in mapped_field_names],
                    'errors': row_errors,
                }
            )

        return preview_entries, mapped_field_names


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
            .prefetch_related('plasmids', 'files', 'attachments__uploaded_by')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        strain = context['strain']
        context['history'] = ActivityLog.objects.filter(
            model_name='Strain',
            object_id=str(strain.pk),
            research_database=strain.research_database,
        )[:20]
        active_database = self.get_active_database()
        context['custom_field_values'] = get_custom_field_values(strain)
        context['attachment_upload_form'] = StrainAttachmentUploadForm()
        context['can_upload_attachments'] = active_database.can_edit(self.request.user)
        context['can_delete_attachments'] = _can_delete_attachments(active_database, self.request.user)
        context['allowed_text_extensions'] = ['csv', 'txt', 'tsv']
        return context


class UploadStrainAttachmentView(LoginRequiredMixin, EditorRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        active_database = self.get_active_database()
        strain = get_object_or_404(Strain, pk=kwargs['pk'], research_database=active_database, is_active=True)
        form = StrainAttachmentUploadForm(request.POST, request.FILES)

        if not form.is_valid():
            messages.error(request, 'Please select at least one valid file to upload.')
            return HttpResponseRedirect(reverse('strain-detail', kwargs={'pk': strain.pk}))

        uploaded_files = form.cleaned_data['files']
        for uploaded_file in uploaded_files:
            attachment = StrainAttachment.objects.create(
                strain=strain,
                uploaded_by=request.user,
                file=uploaded_file,
            )
            AuditLog.objects.create(
                user=request.user,
                action='upload_attachment',
                record_type='StrainAttachment',
                record_id=str(attachment.pk),
                metadata={
                    'strain_id': strain.strain_id,
                    'filename': attachment.file_name,
                    'size': attachment.file_size,
                },
            )

        messages.success(request, f'Uploaded {len(uploaded_files)} attachment(s) for strain {strain.strain_id}.')
        return HttpResponseRedirect(reverse('strain-detail', kwargs={'pk': strain.pk}))


class DeleteStrainAttachmentView(LoginRequiredMixin, DatabasePermissionMixin, View):
    required_permission = 'view'

    def post(self, request, *args, **kwargs):
        active_database = self.get_active_database()
        if not _can_delete_attachments(active_database, request.user):
            return HttpResponseForbidden('Only database owner/admin can delete attachments.')

        attachment = get_object_or_404(
            StrainAttachment.objects.select_related('strain'),
            pk=kwargs['attachment_pk'],
            strain__pk=kwargs['pk'],
            strain__research_database=active_database,
            strain__is_active=True,
        )
        strain = attachment.strain
        filename = attachment.file_name
        attachment.file.delete(save=False)
        attachment.delete()

        AuditLog.objects.create(
            user=request.user,
            action='delete_attachment',
            record_type='StrainAttachment',
            record_id=str(kwargs['attachment_pk']),
            metadata={
                'strain_id': strain.strain_id,
                'filename': filename,
            },
        )

        messages.success(request, f'Deleted attachment {filename}.')
        return HttpResponseRedirect(reverse('strain-detail', kwargs={'pk': strain.pk}))


class StrainAttachmentDownloadView(LoginRequiredMixin, DatabasePermissionMixin, View):
    required_permission = 'view'

    def get(self, request, *args, **kwargs):
        active_database = self.get_active_database()
        attachment = get_object_or_404(
            StrainAttachment.objects.select_related('strain'),
            pk=kwargs['attachment_pk'],
            strain__pk=kwargs['pk'],
            strain__research_database=active_database,
            strain__is_active=True,
        )
        if not attachment.file:
            raise Http404('Attachment file is missing.')
        return FileResponse(attachment.file.open('rb'), as_attachment=True, filename=attachment.file_name)


class StrainHistoryView(LoginRequiredMixin, DatabasePermissionMixin, CurrentDatabaseQuerysetMixin, DetailView):
    model = Strain
    template_name = 'research/strain_history.html'
    context_object_name = 'strain'
    required_permission = 'view'

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True).select_related('created_by')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['versions'] = self.object.versions.select_related('changed_by').order_by('-changed_at')
        return context


class StrainVersionDetailView(LoginRequiredMixin, DatabasePermissionMixin, CurrentDatabaseQuerysetMixin, DetailView):
    model = StrainVersion
    pk_url_kwarg = 'version_pk'
    template_name = 'research/strain_version_detail.html'
    context_object_name = 'version'
    required_permission = 'view'

    def get_queryset(self):
        active_database = self.get_active_database()
        return (
            StrainVersion.objects.select_related('strain', 'changed_by')
            .filter(
                strain__research_database=active_database,
                strain__is_active=True,
                strain_id=self.kwargs['pk'],
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        version = self.object
        newer_version = (
            version.strain.versions.filter(changed_at__gt=version.changed_at)
            .order_by('changed_at')
            .first()
        )
        comparison_snapshot = newer_version.snapshot if newer_version else serialize_strain_snapshot(version.strain)
        diff_map = compare_versions(version.snapshot, comparison_snapshot)
        context['strain'] = version.strain
        context['comparison_target'] = newer_version
        context['can_restore'] = self.get_active_database().can_edit(self.request.user)
        context['diff_items'] = [
            {
                'field': field_name,
                'old': values['old'],
                'new': values['new'],
            }
            for field_name, values in diff_map.items()
        ]
        return context


class RestoreVersionView(LoginRequiredMixin, EditorRequiredMixin, CurrentDatabaseQuerysetMixin, View):
    def post(self, request, *args, **kwargs):
        active_database = self.get_active_database()
        strain = get_object_or_404(Strain, pk=kwargs['pk'], research_database=active_database, is_active=True)
        version = get_object_or_404(StrainVersion, pk=kwargs['version_pk'], strain=strain)
        snapshot = version.snapshot or {}

        standard_fields = {
            field.name
            for field in Strain._meta.fields
            if field.name not in {'id', 'created_at', 'updated_at', 'created_by'}
        }

        with transaction.atomic():
            for field_name in standard_fields:
                if field_name == 'research_database':
                    continue
                if field_name not in snapshot:
                    continue
                setattr(strain, field_name, snapshot.get(field_name))

            strain.save(changed_by=request.user)

            plasmid_ids = snapshot.get('plasmids', []) or []
            valid_plasmid_ids = Plasmid.objects.filter(
                research_database=active_database,
                id__in=plasmid_ids,
            ).values_list('id', flat=True)
            strain.plasmids.set(valid_plasmid_ids)

            custom_snapshot = snapshot.get('custom_fields') or {}
            definitions = {
                definition.name: definition
                for definition in CustomFieldDefinition.objects.filter(research_database=active_database)
            }
            for definition in definitions.values():
                CustomFieldValue.objects.filter(strain=strain, field_definition=definition).delete()

            for field_name, value in custom_snapshot.items():
                definition = definitions.get(field_name)
                if definition is None:
                    continue
                custom_value = CustomFieldValue(strain=strain, field_definition=definition)
                if definition.field_type == CustomFieldDefinition.FieldType.TEXT:
                    custom_value.value_text = value
                elif definition.field_type == CustomFieldDefinition.FieldType.NUMBER:
                    custom_value.value_number = value
                elif definition.field_type == CustomFieldDefinition.FieldType.DATE:
                    custom_value.value_date = date.fromisoformat(value) if isinstance(value, str) and value else value
                elif definition.field_type == CustomFieldDefinition.FieldType.BOOLEAN:
                    custom_value.value_boolean = value
                elif definition.field_type == CustomFieldDefinition.FieldType.CHOICE:
                    custom_value.value_choice = value
                custom_value.save()

            AuditLog.objects.create(
                user=request.user,
                action='restore_version',
                record_type='Strain',
                record_id=str(strain.pk),
                metadata={
                    'version_id': version.pk,
                    'strain_id': strain.strain_id,
                },
            )

        messages.success(request, f'Strain {strain.strain_id} restored from version {version.pk}.')
        return HttpResponseRedirect(reverse('strain-history', kwargs={'pk': strain.pk}))


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
