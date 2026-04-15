from django.urls import path
from . import views

urlpatterns = [
    path('',                                           views.checkout,           name='checkout'),
    path('checkout/place-order/',                      views.place_order,        name='place_order'),
    path('checkout/success/<str:order_number>/',       views.order_success,      name='order_success'),

    path('address/add/',                               views.address_add,        name='address_add'),
    path('address/<int:pk>/edit/',                     views.address_edit,       name='address_edit'),
    path('address/<int:pk>/set-default/',              views.address_set_default, name='address_set_default'),
]