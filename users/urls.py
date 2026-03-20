from django.urls import path, include
from . import views

urlpatterns = [    

    path('',views.home_view,name='home'),
    path('login/',views.login_view,name='login'),
    path('logout/',views.logout_view,name='logout'),
    path('signup/',views.signup_view,name='signup'),
    path('signup/verify-otp/', views.verify_signup_otp, name='verify_signup_otp'),
    path('otp/resend/', views.resend_otp, name='resend_otp'),
    path("forgot-password/",views.forgot_password,name="forgot_password"),


]