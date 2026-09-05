from django.urls import path
from . import views

urlpatterns = [
    path("",                    views.admin_dashboard,      name="admin_dashboard"),
    path("chart-data/",         views.dashboard_chart_data, name="dashboard_chart_data"),
    path("sales-report/",       views.sales_report,         name="sales_report"),         
    path("sales-report/pdf/",   views.sales_report_pdf,     name="sales_report_pdf"),    
    path('dashboard/report/download/', views.dashboard_report_download, name='dashboard_report_download'),

]