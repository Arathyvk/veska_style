from django.urls import path
from .import views  

urlpatterns = [
    
    path('', views.user_coupon_list, name='user_coupon_list'),
    path('ajax/', views.user_coupons_ajax, name='user_coupons_ajax'),
    path('apply/', views.apply_coupon, name='apply_coupon'),
    path('remove/', views.remove_coupon, name='remove_coupon'),
    path('test/', views.test_coupon_api, name='test_coupon_api'),
    
]