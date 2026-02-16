from django.urls import path

from .views import (
    DashboardView,
    DatabaseMembershipListView,
    DatabaseMembershipUpdateRoleView,
    FileDetailView,
    LocationDetailView,
    OrganismDetailView,
    PlasmidDetailView,
    SearchResultsView,
    SelectDatabaseView,
    StrainCreateView,
    StrainDeleteView,
    StrainDetailView,
    StrainListView,
    StrainUpdateView,
    SwitchDatabaseView,
)

urlpatterns = [
    path('databases/select/', SelectDatabaseView.as_view(), name='database-select'),
    path('databases/switch/', SwitchDatabaseView.as_view(), name='database-switch'),
    path('databases/switch/<int:database_id>/', SwitchDatabaseView.as_view(), name='database-switch-id'),
    path('databases/memberships/', DatabaseMembershipListView.as_view(), name='membership-list'),
    path(
        'databases/memberships/<int:membership_id>/role/',
        DatabaseMembershipUpdateRoleView.as_view(),
        name='membership-update-role',
    ),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('search/', SearchResultsView.as_view(), name='search-results'),
    path('strains/', StrainListView.as_view(), name='strain-list'),
    path('strains/create/', StrainCreateView.as_view(), name='strain-create'),
    path('strains/<int:pk>/', StrainDetailView.as_view(), name='strain-detail'),
    path('strains/<int:pk>/update/', StrainUpdateView.as_view(), name='strain-update'),
    path('strains/<int:pk>/delete/', StrainDeleteView.as_view(), name='strain-delete'),
    path('organisms/<int:pk>/', OrganismDetailView.as_view(), name='organism-detail'),
    path('plasmids/<int:pk>/', PlasmidDetailView.as_view(), name='plasmid-detail'),
    path('locations/<int:pk>/', LocationDetailView.as_view(), name='location-detail'),
    path('files/<int:pk>/', FileDetailView.as_view(), name='file-detail'),
]
