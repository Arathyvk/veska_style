from django.urls import path
from . import views

urlpatterns = [
    path('',views.product_list,name='product_list'),
    path('add/',views.product_add,name='product_add'),
    path('<uuid:uuid>/edit/',views.product_edit,name='product_edit'),
]