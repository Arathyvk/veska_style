from django.urls import path
from . import views

urlpatterns = [

     path('',views.admin_order_list,name='admin_order_list'),
     path('orders/<str:order_number>/',views.order_detail,name='admin_order_detail'),
     path('orders/<str:order_number>/status/',views.order_update_status,name='admin_order_update_status'),
     path('inventory/',views.inventory_list,name='admin_inventory_list'),
     path('inventory/<int:product_id>/',views.inventory_detail,name='admin_inventory_detail'),
     path('inventory/<int:product_id>/stock/',views.inventory_update_stock,name='admin_inventory_update_stock'),
     path('inventory/<int:product_id>/status/',views.inventory_toggle_status,name='admin_inventory_toggle_status'),
     path('<int:order_id>/items/<int:item_id>/return/',views.return_request, name='return_request'),


]