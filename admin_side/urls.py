from django.urls import path
from . import views

urlpatterns = [
    path('',views.admin_login,name='admin_login'),
    path('logout/',views.admin_logout,name='admin_logout'),
    path('users/',views.user_list,name='user_list'),
    path('users/<uuid:uuid>/block/',views.block_user,name='block_user'),
    path('users/<uuid:uuid>/unblock/',views.unblock_user,name='unblock_user'),
]

