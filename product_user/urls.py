from django.urls import path
from . import views

urlpatterns = [
    path('',               views.product_shop,   name='product_shop'),
    path('<slug:slug>/',   views.product_detail, name='product_detail'),
]