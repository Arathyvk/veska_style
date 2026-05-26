from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/',            views.admin_dashboard,     name='admin_dashboard'),
    path('dashboard/chart-data/', views.dashboard_chart_data, name='dashboard_chart_data'),
]