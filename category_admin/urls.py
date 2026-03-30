from django.urls import path
from . import views

urlpatterns = [
    path('categories/',views.category_list,name='admin_category_list'),
    path('categories/add/',views.category_add,name='admin_category_add'),


]