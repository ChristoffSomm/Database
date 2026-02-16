from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from .models import DatabaseMembership, Organism, Plasmid, ResearchDatabase, Strain
from .utils import SESSION_DATABASE_KEY, get_current_database


class CurrentDatabaseQuerysetMixin:
    """Filter list/detail querysets to the active research database."""

    def get_current_database(self):
        return getattr(self.request, 'current_database', None) or get_current_database(self.request)

    def get_queryset(self):
        queryset = super().get_queryset()
        current_database = self.get_current_database()
        if current_database is None:
            return queryset.none()
        return queryset.filter(database=current_database)


class DatabasePermissionMixin:
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if self.allowed_roles:
            current_database = getattr(request, 'current_database', None) or get_current_database(request)
            membership = DatabaseMembership.objects.filter(user=request.user, database=current_database).first()
            if not membership or membership.role not in self.allowed_roles:
                raise PermissionDenied('Insufficient permissions for this database.')
        return super().dispatch(request, *args, **kwargs)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'research/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_database = getattr(self.request, 'current_database', None) or get_current_database(self.request)
        strains = Strain.objects.filter(database=current_database)
        organisms = Organism.objects.filter(database=current_database)
        plasmids = Plasmid.objects.filter(database=current_database)

        context['strain_count'] = strains.count()
        context['organism_count'] = organisms.count()
        context['plasmid_count'] = plasmids.count()
        context['pending_count'] = strains.filter(status=Strain.Status.PENDING).count()
        context['approved_count'] = strains.filter(status=Strain.Status.APPROVED).count()
        context['archived_count'] = strains.filter(status=Strain.Status.ARCHIVED).count()
        context['recent_organisms'] = organisms.annotate(total=Count('strains')).order_by('-total')[:5]
        return context


class DatabaseSelectView(LoginRequiredMixin, TemplateView):
    template_name = 'research/database_select.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['memberships'] = DatabaseMembership.objects.select_related('database').filter(user=self.request.user)
        context['current_database_id'] = self.request.session.get(SESSION_DATABASE_KEY)
        return context


class SwitchDatabaseView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        database = get_object_or_404(
            ResearchDatabase,
            id=request.POST.get('database_id'),
            memberships__user=request.user,
        )
        request.session[SESSION_DATABASE_KEY] = database.id
        next_url = request.POST.get('next') or reverse('dashboard')
        return redirect(next_url)


class DatabaseMembershipListView(LoginRequiredMixin, DatabasePermissionMixin, ListView):
    template_name = 'research/membership_list.html'
    context_object_name = 'memberships'
    allowed_roles = (DatabaseMembership.Role.ADMIN,)

    def get_queryset(self):
        current_database = getattr(self.request, 'current_database', None) or get_current_database(self.request)
        return DatabaseMembership.objects.filter(database=current_database).select_related('user', 'database')


class DatabaseMembershipUpdateRoleView(LoginRequiredMixin, DatabasePermissionMixin, View):
    allowed_roles = (DatabaseMembership.Role.ADMIN,)

    def post(self, request, *args, **kwargs):
        current_database = getattr(request, 'current_database', None) or get_current_database(request)
        membership = get_object_or_404(DatabaseMembership, id=kwargs['membership_id'], database=current_database)
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
