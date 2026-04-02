from django.urls import path
from . import views

urlpatterns = [
    # List
    path('',
         views.product_list,
         name='product_list'),

    # Add
    path('add/',
         views.product_add,
         name='product_add'),

    # Edit  — uuid type converter matches models.UUIDField
    path('<uuid:uuid>/edit/',
         views.product_edit,
         name='product_edit'),

    # Remove (soft-delete, POST only)
    path('<uuid:uuid>/remove/',
         views.product_remove,
         name='product_remove'),

    # AJAX image delete
    path('image/<int:pk>/delete/',
         views.image_delete_ajax,
         name='image_delete_ajax'),
]