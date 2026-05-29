from django.urls import path
from . import views

urlpatterns = [
    path('',               views.product_shop,   name='product_shop'),
    path('<slug:slug>/',   views.product_detail, name='product_detail'),
    path('cart/add-with-size/', views.cart_add_with_size, name='cart_add_with_size'),
]