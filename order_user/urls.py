from django.urls import path
from . import views

urlpatterns = [
    path('', views.order_list, name='order_list'),
    path('<str:uuid>/success/', views.order_success, name='order_success'),
    path('<str:uuid>/invoice/', views.download_invoice, name='download_invoice'),
    path('<str:uuid>/cancel/', views.cancel_order, name='cancel_order'),
    
    path('<str:uuid>/return/', views.return_order, name='return_order'),  
    path('<str:short_id>/return/', views.return_order_redirect, name='return_order_old'),
    path('<str:uuid>/cancel-item/<int:item_id>/', views.cancel_order_item, name='cancel_order_item'),
    path('<str:uuid>/items/<int:item_id>/return/', views.return_request, name='return_request'),
    path('orders/<uuid:uuid>/', views.order_detail, name='order_detail'),
    path('orders/<uuid:uuid>/invoice/', views.download_invoice, name='download_invoice'),
    path('submit-review/', views.submit_review, name='submit_review'),
]