from django.urls import path
from . import views

urlpatterns = [
    path('',views.admin_order_list,name='admin_order_list'),
    path('orders/<str:order_number>/',views.admin_order_detail,name='admin_order_detail'),
    path('inventory/',views.admin_inventory,name='admin_inventory'),
    path('stock-update/<int:pk>/',views.admin_stock_update,name='admin_stock_update'),
]