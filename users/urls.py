from django.urls import path, include
from . import views

urlpatterns = [    

    path('',views.home_view,name='home'),
    path('login/',views.login_view,name='login'),
    path('logout/',views.logout_view,name='logout'),
    path('signup/',views.signup_view,name='signup'),




]