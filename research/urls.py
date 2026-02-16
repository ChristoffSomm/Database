from django.urls import path

from .views import DashboardView, StrainDetailView, StrainListView

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('strains/', StrainListView.as_view(), name='strain-list'),
    path('strains/<slug:strain_id>/', StrainDetailView.as_view(), name='strain-detail'),
]
