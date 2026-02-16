from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.views.generic import DetailView, ListView, TemplateView

from .models import Organism, Strain


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'research/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['strain_count'] = Strain.objects.count()
        context['organism_count'] = Organism.objects.count()
        context['active_count'] = Strain.objects.filter(status=Strain.Status.ACTIVE).count()
        context['recent_organisms'] = Organism.objects.annotate(total=Count('strains')).order_by('-total')[:5]
        return context


class StrainListView(LoginRequiredMixin, ListView):
    model = Strain
    template_name = 'research/strain_list.html'
    context_object_name = 'strains'
    paginate_by = 25


class StrainDetailView(LoginRequiredMixin, DetailView):
    model = Strain
    template_name = 'research/strain_detail.html'
    context_object_name = 'strain'
    slug_field = 'strain_id'
    slug_url_kwarg = 'strain_id'
