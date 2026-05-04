from django.urls import path
from . import views
 
urlpatterns = [
    path('wishlist/',views.wishlist_detail,name='wishlist_detail'),
    path('wishlist/toggle/<slug:slug>/',views.wishlist_toggle,name='wishlist_toggle'),
]