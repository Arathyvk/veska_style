from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
 
from cart_user.models import Cart,CartItem
from wishlist_user.models import Wishlist
from product_admin.models import Product
 
FREE_SHIPPING = Decimal('999')
SHIPPING_FEE  = Decimal('79')
TAX_RATE      = Decimal('0')
COUNTRIES = ['India','United States','United Kingdom','UAE','Singapore','Canada','Australia','Other']


def _get_cart(request):
    if request.user.is_authenticated:
        cart,_ = Cart.objects.get_or_create(user=request.user)
        return cart
    
    request.session.save()

    cart,_ = Cart.objects.get_or_create(user=None)
    return cart



def _get_wishlist(request):
    if request.user.is_authenticated:
        wl, _ = Wishlist.objects.get_or_create(user=request.user)
        return wl
    
    return None
 
 
def _wishlist_ids(request):
    wl = _get_wishlist(request)
    if not  wl:
        return set()
    return set(wl.products.values_list('id', flat=True))
 


 
@require_POST
def wishlist_toggle(request, slug):
    if not request.user.is_authenticated:
        messages.info(request, 'Please log in to save items to your wishlist.')
        return redirect('login')
 
    product = get_object_or_404(Product, slug=slug, is_active=True)
    wl      = _get_wishlist(request)
 
    if wl.products.filter(pk=product.pk).exists():
        wl.products.remove(product)
        messages.info(request, f'"{product.name}" removed from wishlist.')
    else:
        wl.products.add(product)
        messages.success(request, f'"{product.name}" saved to wishlist!')
  
    return redirect(request.POST.get('next', 'product_shop'))
 

 
@login_required(login_url='login')
def wishlist_detail(request):
    wl = Wishlist.objects.get_or_create(user=request.user)[0]

    products = wl.products.filter(is_active=True)

    cart = _get_cart(request)
    cart_product_ids = set()

    if cart:
        cart_product_ids = set(cart.items.values_list('product_id', flat=True))

    return render(request, 'wishlist.html', {
        'products': products,
        'cart_product_ids': cart_product_ids,
    })


@login_required
def move_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    cart = _get_cart(request)

    item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        defaults={'quantity': 1}
    )

    if not created:
        item.quantity += 1
        item.save()

    wishlist = Wishlist.objects.get(user=request.user)
    wishlist.products.remove(product)

    messages.success(request, f'{product.name} move to cart')

    return redirect('cart_detail')



