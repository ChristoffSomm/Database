from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from .forms import GlobalSearchForm
from .helpers import SESSION_DATABASE_KEY, get_current_database
from .models import DatabaseMembership, File, Location, Organism, Plasmid, ResearchDatabase, Strain


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


class DatabasePermissionMixin:
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if self.allowed_roles:
            current_database = getattr(request, 'current_database', None) or get_current_database(request)
            membership = DatabaseMembership.objects.filter(
                user=request.user,
                research_database=current_database,
            ).first()
            if not membership or membership.role not in self.allowed_roles:
                raise PermissionDenied('Insufficient permissions for this database.')
        return super().dispatch(request, *args, **kwargs)


class EditorRequiredMixin(DatabasePermissionMixin):
    allowed_roles = (DatabaseMembership.Role.ADMIN, DatabaseMembership.Role.EDITOR)


class AdminRequiredMixin(DatabasePermissionMixin):
    allowed_roles = (DatabaseMembership.Role.ADMIN,)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'research/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_database = getattr(self.request, 'current_database', None) or get_current_database(self.request)
        strains = Strain.objects.filter(research_database=current_database)
        organisms = Organism.objects.filter(research_database=current_database)
        plasmids = Plasmid.objects.filter(research_database=current_database)

        context['strain_count'] = strains.count()
        context['organism_count'] = organisms.count()
        context['plasmid_count'] = plasmids.count()
        context['pending_count'] = strains.filter(status=Strain.Status.PENDING).count()
        context['approved_count'] = strains.filter(status=Strain.Status.APPROVED).count()
        context['archived_count'] = strains.filter(status=Strain.Status.ARCHIVED).count()
        context['recent_organisms'] = organisms.annotate(total=Count('strains')).order_by('-total')[:5]
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


class DatabaseMembershipListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    template_name = 'research/membership_list.html'
    context_object_name = 'memberships'

    def get_queryset(self):
        current_database = getattr(self.request, 'current_database', None) or get_current_database(self.request)
        return DatabaseMembership.objects.filter(research_database=current_database).select_related('user', 'research_database')


class DatabaseMembershipUpdateRoleView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        current_database = getattr(request, 'current_database', None) or get_current_database(request)
        membership = get_object_or_404(
            DatabaseMembership,
            id=kwargs['membership_id'],
            research_database=current_database,
        )
        role = request.POST.get('role')
        valid_roles = {choice[0] for choice in DatabaseMembership.Role.choices}
        if role in valid_roles:
            membership.role = role
            membership.save(update_fields=['role'])
            messages.success(request, f'Updated role for {membership.user}.')
        return HttpResponseRedirect(reverse('membership-list'))


class StrainListView(LoginRequiredMixin, CurrentDatabaseQuerysetMixin, ListView):
    model = Strain
    template_name = 'research/strain_list.html'
    context_object_name = 'strains'
    paginate_by = 25


class StrainDetailView(LoginRequiredMixin, CurrentDatabaseQuerysetMixin, DetailView):
    model = Strain
    template_name = 'research/strain_detail.html'
    context_object_name = 'strain'
    slug_field = 'strain_id'
    slug_url_kwarg = 'strain_id'


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


class SearchResultsView(LoginRequiredMixin, TemplateView):
    template_name = 'research/search_results.html'

    def dispatch(self, request, *args, **kwargs):
        current_database = getattr(request, 'current_database', None) or get_current_database(request)
        membership = DatabaseMembership.objects.filter(user=request.user, research_database=current_database).first()
        if current_database is None or membership is None:
            raise PermissionDenied('Insufficient permissions for this database.')
        return super().dispatch(request, *args, **kwargs)

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
                    Strain.objects.filter(research_database=current_database).filter(
                        Q(strain_id__icontains=query) | Q(name__icontains=query)
                    )[:50]
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
