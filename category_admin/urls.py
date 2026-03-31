from django.urls import path
from . import views

urlpatterns = [
    path('categories/',views.category_list,name='admin_category_list'),
    path('categories/add/',views.category_add,name='admin_category_add'),
    path('categories/<int:pk>/edit/',views.category_edit,name='admin_category_edit'),
    path('categories/<int:pk>/block/',views.category_block,name='category_block'),
    path('categories/<int:pk>/unblock/',views.category_unblock,name='category_unblock'),

]