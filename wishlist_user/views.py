from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
 
from cart_user.models import Cart, CartItem
from wishlist_user.models import Wishlist
from product_admin.models import Product
 
FREE_SHIPPING = Decimal('999')
SHIPPING_FEE  = Decimal('79')
TAX_RATE      = Decimal('0')
COUNTRIES = ['India','United States','United Kingdom','UAE','Singapore','Canada','Australia','Other']


def _get_cart(request):
    if not request.session.session_key:
        request.session.create()
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(
            user=request.user,
            defaults={'session_key': request.session.session_key}
        )
        return cart
    cart, _ = Cart.objects.get_or_create(
        session_key=request.session.session_key, user=None
    )
    return cart
 


def _get_wishlist(request):
    if not request.user.is_authenticated:
        return None
    wl, _ = Wishlist.objects.get_or_create(user=request.user)
    return wl


@login_required(login_url='login')
def wishlist_detail(request):
    wl       = _get_wishlist(request)
    products = wl.products.filter(is_active=True).prefetch_related('images','variants') if wl else []
    cart     = _get_cart(request)
    cart_ids = cart.items.values_list('product_id', flat=True)
    return render(request, 'wishlist.html', {
        'products': products, 'cart_product_ids': cart_ids,
    })
 
 
@require_POST
@login_required(login_url='login')
def wishlist_toggle(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    wl      = _get_wishlist(request)
    if wl.products.filter(pk=product.pk).exists():
        wl.products.remove(product)
        messages.success(request, f'"{product.name}" removed from wishlist.')
    else:
        wl.products.add(product)
        messages.success(request, f'"{product.name}" added to wishlist.')
    return redirect(request.POST.get('next') or 'wishlist_detail')
 
 
@require_POST
@login_required(login_url='login')
def wishlist_move_to_cart(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    wl      = _get_wishlist(request)
    cart    = _get_cart(request)
    available = product.total_stock
    if available == 0:
        messages.error(request, f'"{product.name}" is out of stock.')
        return redirect('wishlist_detail')
    item, created = CartItem.objects.get_or_create(
        cart=cart, product=product, variant=None, defaults={'quantity': 0}
    )
    item.quantity = min(item.quantity + 1, available, 10)
    item.save()
    wl.products.remove(product)
    messages.success(request, f'"{product.name}" moved to cart.')
    return redirect('wishlist_detail')