from django.urls import path
from . import views   

urlpatterns = [
    path('',                   views.checkout,                       name='checkout'),

    path('address/add/',                views.address_add,                    name='address_add'),
    path('address/<int:pk>/edit/',      views.address_edit,                   name='address_edit'),
    path('address/<int:pk>/default/',   views.address_set_default,            name='address_set_default'),

    path('coupon/apply/',               views.apply_coupon,                   name='apply_coupon'),
    path('coupon/remove/',              views.remove_coupon,                  name='remove_coupon'),

    path('place-order/',                views.place_order,                    name='place_order'),
    path('stripe/create-checkout/',     views.stripe_create_checkout_session, name='stripe_create_checkout'),
    path('stripe/webhook/',             views.stripe_webhook,                 name='stripe_webhook'),
    path('payment/success/',            views.payment_success,                name='payment_success'),
    path('payment/cancel/',             views.payment_cancel,                 name='payment_cancel'),

     path('order/success/<uuid:uuid>/',  views.order_success,                  name='order_success'),
]