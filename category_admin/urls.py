from django.urls import path
from . import views

urlpatterns = [
    path('',views.category_list,name='category_list'),
    path('add/',views.category_add,name='category_add'),
    path('<uuid:uuid>/edit/',views.category_edit,name='category_edit'),
    path('<uuid:uuid>/block/',views.category_block,name='category_block'),
    path('<uuid:uuid>/unblock/',views.category_unblock,name='category_unblock'),
]