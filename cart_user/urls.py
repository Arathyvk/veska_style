from django.urls import path
from . import views

urlpatterns = [
    path('cart/',views.cart_detail,name='cart_detail'),
    path('cart/add/<slug:slug>/',views.cart_add,name='cart_add'),
    path('cart/update/<int:item_id>/',views.cart_update,name='cart_update'),
    path('cart/remove/<int:item_id>/',views.cart_remove,name='cart_remove'),
    path('wishlist/',views.wishlist_detail,name='wishlist_detail'),
    path('wishlist/toggle/<slug:slug>/',views.wishlist_toggle,name='wishlist_toggle'),
    path('<slug:slug>/review/',views.submit_review,name='submit_review'),
]