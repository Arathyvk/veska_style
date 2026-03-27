from django.urls import path
from . import views

urlpatterns = [    
    path('profile/', views.account_profile, name='account_profile'),
    path('address/', views.account_address, name='account_address'),
    path('address/add/', views.account_address_add, name='account_address_add'),
    path('email/',views.account_change_email,name='account_change_email'),
    path('email/verify/',views.account_change_email_verify,name='account_change_email_verify'),
    path('email/resend/',views.account_change_email_resend,name='account_change_email_resend'),
    
]