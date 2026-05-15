from django.urls import path
from .import views

urlpatterns = [
    path('pay/<str:order_number>/',     views.razorpay_create_order, name='razorpay_create_order'),
    path('pay/verify/',                 views.razorpay_verify,       name='razorpay_verify'),
    path('success/<str:order_number>/', views.payment_success,       name='payment_success'),
    path('failure/<str:order_number>/', views.payment_failure,       name='payment_failure'),    
]