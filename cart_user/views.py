from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from cart_user.models import Cart, CartItem, MAX_QTY_PER_ITEM
from product_admin.models import Product, ProductVariant
from wishlist_user.models import Wishlist 

ITEMS_PER_PAGE   = 12
MAX_QTY_PER_ITEM = 10
FREE_SHIPPING    = 999
SHIPPING_FEE     = 79

 
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
 
 
def _wishlist_ids(request):
    wl = _get_wishlist(request)
    if wl is None:
        return set()
    return set(wl.products.values_list('id', flat=True))
 



@require_POST
def cart_add(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
 
    if product.total_stock == 0:
        messages.error(request, f'"{product.name}" is out of stock.')
        return redirect(request.POST.get('next', 'product_shop'))
 
    size    = request.POST.get('size', '').strip()
    variant = None
    if size:
        variant = ProductVariant.objects.filter(product=product, size=size).first()
        if variant and variant.stock == 0:
            messages.error(request, f'Size {size} is out of stock.')
            return redirect(request.POST.get('next', 'product_detail'), slug=slug)
 
    try:
        qty = max(1, int(request.POST.get('quantity', 1)))
    except (ValueError, TypeError):
        qty = 1
 
    cart = _get_cart(request)
    item, created = CartItem.objects.get_or_create(
        cart=cart, product=product, variant=variant,
        defaults={'quantity': 0},
    )
    available = variant.stock if variant else product.total_stock
    new_qty   = item.quantity + qty
    capped    = min(new_qty, available, MAX_QTY_PER_ITEM)
    item.quantity = capped
    item.save()
 
    wl = _get_wishlist(request)
    if wl:
        wl.products.remove(product)
 
    if created:
        messages.success(request, f'"{product.name}" added to cart!')
    else:
        messages.success(request, f'Cart updated — {capped} × {product.name}.')
    if capped < new_qty:
        messages.warning(request, f'Max {MAX_QTY_PER_ITEM} per item allowed.')
 
    return redirect(request.POST.get('next', 'product_shop'))
 

 
def cart_detail(request):
    cart  = _get_cart(request)
    items = list(cart.items.all())
 
    blocked_items  = [i for i in items if not i.is_available]
    ok_items       = [i for i in items if i.is_available]
    can_checkout   = bool(ok_items) and not blocked_items
 
    subtotal       = cart.subtotal
    shipping       = 0 if subtotal >= FREE_SHIPPING else SHIPPING_FEE
    order_total    = subtotal + shipping
    remaining_free = max(0, FREE_SHIPPING - subtotal)

    return render(request, 'cart_detail.html', {
        'cart':               cart,
        'items':              items,
        'unavailable_items':  blocked_items,  
        'available_items':    ok_items,        
        'can_checkout':       can_checkout,
        'subtotal':           subtotal,
        'shipping':           shipping,
        'order_total':        order_total,
        'remaining_free':     remaining_free,
        'max_qty':            MAX_QTY_PER_ITEM,
    })
    

@require_POST
def cart_update(request, item_id):
    cart = _get_cart(request)
    item = get_object_or_404(CartItem, pk=item_id, cart=cart)
 
    action = request.POST.get('action', '')
    if action == 'increase':
        new_qty = item.quantity + 1
    elif action == 'decrease':
        new_qty = item.quantity - 1
    elif action == 'remove':
        item.delete()
        messages.info(request, 'Item removed.')
        return redirect('cart_detail')
    else:
        try:
            new_qty = int(request.POST.get('quantity', item.quantity))
        except (ValueError, TypeError):
            new_qty = item.quantity
 
    if new_qty <= 0:
        item.delete()
        messages.info(request, 'Item removed from cart.')
        return redirect('cart_detail')
 
    available     = item.available_stock
    capped        = min(new_qty, available, MAX_QTY_PER_ITEM)
    item.quantity = capped
    item.save()
    return redirect('cart_detail')
 

@require_POST
def cart_remove(request, item_id):
    cart = _get_cart(request)
    CartItem.objects.filter(pk=item_id, cart=cart).delete()
    messages.success(request, 'Item removed from cart.')
    return redirect('cart_detail')
 
 
@require_POST
def cart_clear(request):
    cart = _get_cart(request)
    cart.items.all().delete()
    messages.success(request, "Cart cleared.")
    return redirect('cart_detail')
  