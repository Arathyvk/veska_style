from django.urls import path
from . import views

urlpatterns = [

     path('',views.admin_order_list,name='admin_order_list'),
     path('admin_orders/<uuid:uuid>/',views.admin_order_detail,name='admin_order_detail'),
     path('orders/<uuid:uuid>/status/',views.order_update_status,name='admin_order_update_status'),
     path('orders/<uuid:uuid>/send_status/',views._send_status_update_email,name='_send_status_update_email'),
     path('inventory/',views.inventory_list,name='admin_inventory_list'),
     path('inventory/<int:product_id>/',views.inventory_detail,name='admin_inventory_detail'),
     path('inventory/<int:product_id>/stock/',views.inventory_update_stock,name='admin_inventory_update_stock'),
     path('inventory/<int:product_id>/status/',views.inventory_toggle_status,name='admin_inventory_toggle_status'),
     path('orders/item/<int:item_id>/cancel/', views.admin_cancel_order_item, name='admin_cancel_order_item'),

    path('order_return/',views.admin_return_list,   name='admin_return_list'),
    path('order_return_detail/<int:pk>/',views.admin_return_detail, name='admin_return_detail'),
    path('order_return_action/<int:pk>/action/',views.admin_return_action, name='admin_return_action'),
    path('order_return_note<int:pk>/add-note/',views.admin_return_add_note, name='admin_return_add_note'),
]
 