 
from django.urls import path
from . import views
 
  
urlpatterns = [
 
    path('wallet/',           views.wallet_dashboard,    name='wallet_dashboard'),
    path('wallet/balance/',   views.wallet_balance_api,  name='wallet_balance_api'),

]