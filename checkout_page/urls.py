from django.urls import path
from . import views
 
urlpatterns = [
    path('', views.checkout, name='checkout'),
 
    path('razorpay/create-order/',  views.razorpay_create_order,  name='razorpay_create_order'),
    path('razorpay/verify/', views.razorpay_verify_payment, name='razorpay_verify_payment'),
 
    path('place-order/', views.place_order, name='place_order'),
 
    path('order/success/<uuid:uuid>/', views.order_success, name='order_success'),
 
    path('apply-coupon/',  views.apply_coupon,  name='apply_coupon'),
    path('remove-coupon/', views.remove_coupon, name='remove_coupon'),
 
    path('address/add/',                  views.address_add,         name='address_add'),
    path('address/<int:pk>/edit/',        views.address_edit,        name='address_edit'),
    path('address/<int:pk>/set-default/', views.address_set_default, name='address_set_default'),
]