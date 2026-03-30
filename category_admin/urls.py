from django.urls import path
from . import views

urlpatterns = [
    path('categories/',views.category_list,name='admin_category_list'),
]