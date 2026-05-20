from django.urls import path
from . import views

urlpatterns = [
    path('checkout/',                        views.checkout,              name='checkout'),
    path('checkout/paypal/create-order/',    views.paypal_create_order,   name='paypal_create_order'),
    path('checkout/paypal/capture-order/',   views.paypal_capture_order,  name='paypal_capture_order'),
 
    path('checkout/place-order/',            views.place_order_cod_wallet, name='place_order'),
 
    path('checkout/success/<uuid:uuid>/',    views.order_success,         name='order_success'),
 
    path('checkout/apply-coupon/',           views.apply_coupon,          name='apply_coupon'),
    path('checkout/remove-coupon/',          views.remove_coupon,         name='remove_coupon'),
 
    path('address/add/',                     views.address_add,           name='address_add'),
    path('address/<int:pk>/edit/',           views.address_edit,          name='address_edit'),
    path('address/<int:pk>/set-default/',    views.address_set_default,   name='address_set_default'),

]