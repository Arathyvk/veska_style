from django.contrib import admin
from django.urls import path,include
from django.conf import settings
from django.conf.urls.static import static
from django.urls import re_path
from django.views.static import serve
handler400 = 'users.views.error_400'
handler403 = 'users.views.error_403'
handler404 = 'users.views.error_404'
handler500 = 'users.views.error_500'


urlpatterns = [
    path('admin/',admin.site.urls),
    path('accounts/',include('allauth.urls')),
    path('',include('users.urls')),
    path('customers/',include('customers.urls')),
    path('newadmin/',include('admin_side.urls')),
    path('category_admin/',include('category_admin.urls')),
    path('product_admin/',include('product_admin.urls')),
    path('product_user/',include('product_user.urls')),
    path('cart_user/',include('cart_user.urls')),
    path('wishlist/',include('wishlist_user.urls')),
    path('checkout/',include('checkout_page.urls')),
    path('order_user/',include('order_user.urls')),
    path('order_admin/',include('order_admin.urls')),
    path('coupon_admin/',include('coupon_admin.urls')),
    path('returns/',include('return_admin.urls')),
    path('about/',include('about_us.urls')),
    path('wallet_user/',include('wallet_user.urls')),
    path('wallet_admin/',include('wallet_admin.urls')),
    path('dashboard/',include('dashboard.urls')),
    path('offer_admin/',include('offer_admin.urls')),

]

# Serve uploaded product images with the local Django server.
urlpatterns += [
    re_path(
        r'^media/(?P<path>.*)$',
        serve,
        {'document_root': settings.MEDIA_ROOT},
    ),
]
