from django.urls import path
from . import views

urlpatterns = [
    path('',                                views.offer_list,          name='offer_list'),
    path('add/',                            views.offer_add,           name='offer_add'),
    path('referral/add/',                   views.referral_offer_add,  name='referral_offer_add'),

    path('<uuid:uuid>/edit/',               views.offer_edit,          name='offer_edit'),
    path('<uuid:uuid>/toggle/',             views.offer_toggle_status, name='offer_toggle_status'),
    path('<uuid:uuid>/delete/',             views.offer_delete,        name='offer_delete'),

    path('referral/stats/',                 views.referral_stats,      name='referral_stats'),
]