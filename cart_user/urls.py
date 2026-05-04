from django.urls import path
from . import views

urlpatterns = [
    path('',views.cart_detail,name='cart_detail'),
    path('cart/add/<slug:slug>/',views.cart_add,name='cart_add'),
    path('cart/update/<int:item_id>/',views.cart_update,name='cart_update'),
    path('cart/remove/<int:item_id>/',views.cart_remove,name='cart_remove'),
    path('cart/clear/',views.cart_clear,name='cart_clear'),

]