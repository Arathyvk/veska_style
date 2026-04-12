from django.urls import path
from . import views

urlpatterns = [
    path('',views.order_list,name='order_list'),
    path('<str:order_number>/',views.order_detail,name='order_detail'),
    path('<str:order_number>/success/',views.order_success,name='order_success'),
    path('<str:order_number>/cancel/',views.cancel_order,name='cancel_order'),
    path('<str:order_number>/cancel-item/<int:item_id>/',views.cancel_order_item,name='cancel_order_item'),
    path('<str:order_number>/return/',views.return_order,name='return_order'),
    path('<str:order_number>/invoice/',views.download_invoice,name='download_invoice'),
]