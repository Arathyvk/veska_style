from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from cart_user.models import Cart, CartItem, MAX_QTY_PER_ITEM
from product_admin.models import Product, ProductVariant, ProductImage




def _get_or_create_cart(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart




@login_required
def cart_detail(request):
    cart  = _get_or_create_cart(request.user)
    items = list(
        cart.items
        .select_related('product', 'variant')
        .prefetch_related('product__images')
        .order_by('id')
    )

    available_items   = [i for i in items if i.is_available]
    unavailable_items = [i for i in items if not i.is_available]
    subtotal          = sum(i.line_total for i in available_items)

    return render(request, 'cart_detail.html', {
        'cart':              cart,
        'items':             items,
        'available_items':   available_items,
        'unavailable_items': unavailable_items,
        'subtotal':          subtotal,
        'MAX_QTY':           MAX_QTY_PER_ITEM,
    })




@require_POST
@login_required
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    _do_add(request, product, variant=None, quantity=1)
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'product_shop'
    return redirect(next_url)



@require_POST
@login_required
def cart_add_by_slug(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)

    try:
        quantity = max(1, int(request.POST.get('quantity', 1)))
    except (ValueError, TypeError):
        quantity = 1

    size    = request.POST.get('size', '').strip()
    variant = None
    if size:
        variant = ProductVariant.objects.filter(product=product, size=size).first()
        if not variant:
            messages.error(request, f'Size "{size}" is not available.')
            return redirect('product_detail', slug=slug)

    _do_add(request, product, variant=variant, quantity=quantity)
    next_url = request.POST.get('next') or 'product_detail'
    if next_url == 'product_detail':
        return redirect('product_detail', slug=slug)
    return redirect(next_url)



def _do_add(request, product, variant, quantity):
    stock = variant.stock if variant else product.total_stock
    if stock <= 0:
        messages.error(request, f'"{product.name}" is out of stock.')
        return

    cart    = _get_or_create_cart(request.user)
    max_qty = min(stock, MAX_QTY_PER_ITEM)

    try:
        item     = CartItem.objects.get(cart=cart, product=product, variant=variant)
        new_qty  = item.quantity + quantity
        if item.quantity >= max_qty:
            messages.warning(
                request,
                f'Maximum allowed quantity ({max_qty}) already in your cart for "{product.name}".'
            )
            return
        item.quantity = min(new_qty, max_qty)
        item.save(update_fields=['quantity'])
        messages.success(request, f'"{product.name}" quantity updated to {item.quantity}.')

    except CartItem.DoesNotExist:
        CartItem.objects.create(
            cart=cart, product=product,
            variant=variant, quantity=min(quantity, max_qty)
        )
        messages.success(request, f'"{product.name}" added to your cart.')






@require_POST
@login_required
def remove_from_cart(request, item_id):
    item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    name = item.product.name
    item.delete()
    messages.success(request, f'"{name}" removed from your cart.')
    return redirect('cart_detail')





@require_POST
@login_required
def update_cart_item(request, item_id):
    item    = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    action  = request.POST.get('action')
    stock   = item.available_stock
    max_qty = min(stock, MAX_QTY_PER_ITEM)

    if action == 'increment':
        if item.quantity >= max_qty:
            messages.warning(request, f'Maximum quantity ({max_qty}) reached.')
        else:
            item.quantity += 1
            item.save(update_fields=['quantity'])

    elif action == 'decrement':
        if item.quantity <= 1:
            name = item.product.name
            item.delete()
            messages.success(request, f'"{name}" removed from your cart.')
            return redirect('cart_detail')
        item.quantity -= 1
        item.save(update_fields=['quantity'])

    elif action == 'set':
        try:
            new_qty = int(request.POST.get('quantity', 1))
        except (ValueError, TypeError):
            messages.error(request, 'Invalid quantity.')
            return redirect('cart_detail')
        if new_qty < 1:
            name = item.product.name
            item.delete()
            messages.success(request, f'"{name}" removed from your cart.')
            return redirect('cart_detail')
        if new_qty > max_qty:
            messages.warning(request, f'Quantity capped at {max_qty}.')
            new_qty = max_qty
        item.quantity = new_qty
        item.save(update_fields=['quantity'])

    return redirect('cart_detail')




@require_POST
@login_required
def clear_cart(request):
    _get_or_create_cart(request.user).items.all().delete()
    messages.success(request, 'Your cart has been cleared.')
    return redirect('cart_detail')