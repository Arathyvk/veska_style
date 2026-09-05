from django.urls import path
from . import views

urlpatterns = [
    path('', views.wishlist_detail, name='wishlist_detail'),
    path('toggle/<slug:slug>/', views.wishlist_toggle, name='wishlist_toggle'),
    path('remove/<slug:slug>/', views.remove_wishlist_item, name='remove_wishlist_item'),  
    path('count/', views.wishlist_count, name='wishlist_count'),                            
    path('move-to-cart/<int:product_id>/', views.move_to_cart, name='move_to_cart'),
]