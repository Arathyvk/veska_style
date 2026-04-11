from django.urls import path
from . import views
 
 
urlpatterns = [
  
    path('',views.order_list,name='order_list'),
    path('<str:order_number>/',views.order_detail,name='order_detail'),
    path('<str:order_number>/success/',views.order_success,name='order_success'),
    path('<str:order_number>/cancel/',views.order_cancel,name='order_cancel'),
    path('<str:order_number>/return/',views.order_return,name='order_return'),
    path('<str:order_number>/invoice/',views.order_invoice,name='order_invoice'),
    path('<str:order_number>/items/<int:item_id>/cancel/', views.order_item_cancel,name='order_item_cancel'),
]
 