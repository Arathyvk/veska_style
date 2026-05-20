from django.urls import path
from . import views

urlpatterns = [

    path('admin/wallets/',views.admin_wallet_list,name='admin_wallet_list'),
    path('admin/wallets/<int:wallet_id>/',views.admin_wallet_detail,name='admin_wallet_detail'),
    path('admin/wallets/<int:wallet_id>/adjust/',views.admin_wallet_adjust,name='admin_wallet_adjust'),
    path('admin/orders/<int:order_id>/approve-return/',views.admin_approve_return,name='admin_approve_return'),
    
]