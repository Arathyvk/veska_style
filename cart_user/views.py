from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponseRedirect
from django.views.decorators.http import require_POST

from cart_user.models import Cart, CartItem, MAX_QTY_PER_ITEM
from cart_user.cart_helpers import get_cart, cart_count_payload, wants_json
from product_admin.models import Product, ProductVariant
from wishlist_user.models import Wishlist

FREE_SHIPPING = 99
SHIPPING_FEE  = 79




def _get_cart(request):
    return get_cart(request)


def _get_wishlist(request):
    if request.user.is_authenticated:
        wl, _ = Wishlist.objects.get_or_create(user=request.user)
        return wl
    return None


def _wishlist_ids(request):
    wl = _get_wishlist(request)
    if not wl:
        return set()
    return set(wl.products.values_list('id', flat=True))


def _safe_next(request, slug):
    raw = request.POST.get('next', '').strip()
    if raw and raw.startswith('/') and '[object' not in raw:
        return raw
    return f'/product_user/{slug}/'


def _json_or_redirect(request, cart, redirect_to, message=None, level='success', extra=None):
    if wants_json(request):
        payload = cart_count_payload(request, cart)
        if message:
            payload['message'] = message
        if extra:
            payload.update(extra)
        return JsonResponse(payload)
    if message:
        getattr(messages, level)(request, message)
    return HttpResponseRedirect(redirect_to) if redirect_to.startswith('/') else redirect(redirect_to)




def get_cart_count(request):
    cart = _get_cart(request)
    return JsonResponse(cart_count_payload(request, cart))



@require_POST
def cart_add(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    action  = request.POST.get('action', 'add_cart')   
    next_url = _safe_next(request, slug)

    if product.total_stock == 0:
        return _json_or_redirect(
            request, _get_cart(request), next_url,
            f'"{product.name}" is out of stock.', 'error',
        )

    size    = request.POST.get('size', '').strip()
    variant = None
    if size:
        variant = ProductVariant.objects.filter(product=product, size=size).first()
        if variant is None:
            return _json_or_redirect(
                request, _get_cart(request), next_url,
                f'Size "{size}" is not available.', 'error',
            )
        if variant.stock == 0:
            return _json_or_redirect(
                request, _get_cart(request), next_url,
                f'Size {size} is out of stock.', 'error',
            )

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


    if capped < new_qty:
        warn_msg = (
            f'Only {capped} unit(s) of "{product.name}" are available; '
            f'cart set to {capped}.'
        )
        if wants_json(request):
            payload = cart_count_payload(request, cart)
            payload['message'] = warn_msg
            payload['warning'] = True
            return JsonResponse(payload)
        messages.warning(request, warn_msg)
    else:
        msg = (
            f'"{product.name}" added to your cart!'
            if created
            else f'Cart updated — {capped} × {product.name}.'
        )
        if wants_json(request):
            payload = cart_count_payload(request, cart)
            payload['message'] = msg
            return JsonResponse(payload)
        messages.success(request, msg)

    if action == 'buy_now':
        return redirect('checkout')
    return redirect('cart_detail')



def cart_detail(request):
    cart  = _get_cart(request)
    items = list(cart.items.select_related('product', 'variant').all())

    blocked_items = [i for i in items if not i.is_available]
    ok_items      = [i for i in items if i.is_available]
    can_checkout  = bool(ok_items) and not blocked_items

    subtotal       = cart.subtotal
    shipping       = 0 if subtotal >= FREE_SHIPPING else SHIPPING_FEE
    order_total    = subtotal + shipping
    remaining_free = max(0, FREE_SHIPPING - subtotal)

    return render(request, 'cart_detail.html', {
        'cart':              cart,
        'items':             items,
        'unavailable_items': blocked_items,
        'available_items':   ok_items,
        'can_checkout':      can_checkout,
        'subtotal':          subtotal,
        'shipping':          shipping,
        'order_total':       order_total,
        'remaining_free':    remaining_free,
        'max_qty':           MAX_QTY_PER_ITEM,
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
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Item removed from cart',
                'cart_count': cart.total_items,
                'cart_subtotal': str(cart.subtotal),
                'grand_total': str(cart.subtotal + (0 if cart.subtotal >= FREE_SHIPPING else SHIPPING_FEE))
            })
        messages.success(request, 'Item removed from cart.')
        return redirect('cart_detail')
    else:
        try:
            new_qty = int(request.POST.get('quantity', item.quantity))
        except (ValueError, TypeError):
            new_qty = item.quantity
    
    if new_qty <= 0:
        item.delete()
        message = 'Item removed from cart.'
        new_quantity = 0
    else:
        available = item.available_stock
        if available <= 0:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': f'"{item.product.name}" is out of stock.'
                }, status=400)
            messages.error(request, f'"{item.product.name}" is out of stock.')
            return redirect('cart_detail')
        
        capped = min(new_qty, available, MAX_QTY_PER_ITEM)
        if capped < new_qty:
            message = f'Only {capped} unit(s) available for "{item.product.name}".'
        else:
            message = f'Quantity updated to {capped}'
        
        item.quantity = capped
        item.save()
        new_quantity = capped
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity,
            'message': message,
            'cart_count': cart.total_items,
            'cart_subtotal': str(cart.subtotal),
            'grand_total': str(cart.subtotal + (0 if cart.subtotal >= FREE_SHIPPING else SHIPPING_FEE)),
            'item_total': str(item.line_total if new_quantity > 0 else 0)
        })
    
    messages.success(request, message)
    return redirect('cart_detail')



@require_POST
def cart_remove(request, item_id):
    cart = _get_cart(request)
    CartItem.objects.filter(pk=item_id, cart=cart).delete()
    return _json_or_redirect(
        request, cart, 'cart_detail',
        'Item removed from cart.', 'success', {'reload': True},
    )



@require_POST
def cart_clear(request):
    cart = _get_cart(request)
    cart.items.all().delete()
    return _json_or_redirect(
        request, cart, 'cart_detail',
        'Cart cleared.', 'success', {'reload': True},
    )