from django.urls import path
from .import views

urlpatterns = [
    path('failure/<str:order_number>/', views.payment_failure,       name='payment_failure'),    
    path('failure/',views.payment_failure,name='payment_failure'),


]
