from django.contrib import admin
from django.urls import path,include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/',admin.site.urls),
    path('accounts/',include('allauth.urls')),
    path('',include('users.urls')),
    path('customers/',include('customers.urls')),
    path('newadmin/',include('admin_side.urls')),
    path('category_admin/',include('category_admin.urls')),
    path('product_admin/',include('product_admin.urls')),
    path('product_user/',include('product_user.urls')),

]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
