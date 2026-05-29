from django.urls import path
from . import views


urlpatterns = [
    path('offers/', views.offer_list, name='offer_list'),
    path('offers/add/', views.offer_add, name='offer_add'),
    path('offers/referral/add/', views.referral_offer_add, name='referral_offer_add'),
    path('offers/<uuid:uuid>/edit/', views.offer_edit, name='offer_edit'),
    path('offers/<uuid:uuid>/toggle/', views.offer_toggle_status, name='offer_toggle'),
    path('offers/<uuid:uuid>/delete/', views.offer_delete, name='offer_delete'),
    path('referral/stats/', views.referral_stats, name='referral_stats'),
    
]