from django.urls import path
from . import views

urlpatterns = [    
    path('profile/', views.account_profile, name='account_profile'),
    path('address/', views.account_address, name='account_address'),
    path('address/add/', views.account_address_add, name='account_address_add'),
    # path('address/<int:pk>/edit/', views.account_address_edit, name='account_address_edit'),
    # path('address/<int:pk>/delete/', views.account_address_delete, name='account_address_delete'),
    # path('address/<int:pk>/set-default/', views.account_address_set_default, name='account_address_set_default'),
]