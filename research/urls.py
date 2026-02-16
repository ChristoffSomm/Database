from django.urls import path

from .views import (
    DashboardView,
    DatabaseMembershipListView,
    DatabaseMembershipUpdateRoleView,
    DatabaseSelectView,
    StrainDetailView,
    StrainListView,
    SwitchDatabaseView,
)

urlpatterns = [
    path('databases/select/', DatabaseSelectView.as_view(), name='database-select'),
    path('databases/switch/', SwitchDatabaseView.as_view(), name='database-switch'),
    path('databases/memberships/', DatabaseMembershipListView.as_view(), name='membership-list'),
    path(
        'databases/memberships/<int:membership_id>/role/',
        DatabaseMembershipUpdateRoleView.as_view(),
        name='membership-update-role',
    ),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('strains/', StrainListView.as_view(), name='strain-list'),
    path('strains/<slug:strain_id>/', StrainDetailView.as_view(), name='strain-detail'),
]
