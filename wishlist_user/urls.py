from django.urls import path
from . import views
 
urlpatterns = [
    path('wishlist/',                              views.wishlist_detail,      name='wishlist_detail'),
    path('wishlist/toggle/<slug:slug>/',           views.wishlist_toggle,      name='wishlist_toggle'),
    path('wishlist/move-to-cart/<slug:slug>/',     views.wishlist_move_to_cart, name='wishlist_move_to_cart'),

]