from django.urls import path
from . import views

urlpatterns = [
    path('',                       views.checkout,           name='checkout'),
    path('checkout/place-order/',           views.place_order,        name='place_order'),
    # path('checkout/apply-coupon/',          views.apply_coupon,       name='apply_coupon'),
    # path('checkout/remove-coupon/',         views.remove_coupon,      name='remove_coupon'),

    path('order/<str:order_number>/success/', views.order_success,    name='order_success'),
    path('order/<str:order_number>/',         views.order_detail,     name='order_detail'),

    path('address/add/',                    views.address_add,        name='address_add'),
    path('address/<int:pk>/edit/',          views.address_edit,       name='address_edit'),
    path('address/<int:pk>/default/',       views.address_set_default, name='address_set_default'),
]