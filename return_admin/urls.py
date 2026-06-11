from django.urls import path
from . import views

urlpatterns = [
    path('',views.admin_return_list,   name='admin_return_list'),
    path('<int:pk>/',views.admin_return_detail, name='admin_return_detail'),
    path('<int:pk>/action/',views.admin_return_action, name='admin_return_action'),
    path('<int:pk>/add-note/',views.admin_return_add_note, name='admin_return_add_note'),
]
 