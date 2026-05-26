from django.urls import path
from .import views  
 
urlpatterns = [
    path('payment/success/<str:uuid>/', views.payment_success, name='payment_success'),
    path('failure/', views.payment_failure, name='payment_failure'),
    path('failure/<str:uuid>/', views.payment_failure_with_order, name='payment_failure_with_order'),
    path('razorpay/success/', views.razorpay_payment_success, name='razorpay_payment_success'),
    path('razorpay/verify-payment/', views.razorpay_verify_payment, name='razorpay_verify_payment'),

]
 