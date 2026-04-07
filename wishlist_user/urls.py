from django.urls import path
from cart_user import views

urlpatterns = [
    # ── Wishlist ──────────────────────────────────────────
    path('wishlist/',                views.wishlist_detail, name='wishlist_detail'),
    path('wishlist/toggle/<slug:slug>/', views.wishlist_toggle, name='wishlist_toggle'),

    # ── Cart ──────────────────────────────────────────────
    path('cart/',                        views.cart_detail,  name='cart_detail'),
    path('cart/add/<slug:slug>/',        views.cart_add,     name='cart_add'),

#     # ── Shop & Detail (already exist, just confirm names) ─
#     path('shop/',                        views.product_shop,   name='product_shop'),
#     path('shop/<slug:slug>/',            views.product_detail, name='product_detail'),
#     path('',                             views.home,           name='home'),
 ]