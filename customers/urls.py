from django.urls import path
from . import views

urlpatterns = [    

    path('profile/',views.account_profile,name='account_profile'),
    

]