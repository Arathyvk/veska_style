from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from cart_user.models import Cart, CartItem, MAX_QTY_PER_ITEM
from product_admin.models import Product, ProductVariant




def _get_or_create_cart(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart




@login_required
def cart_detail(request):
    cart  = _get_or_create_cart(request.user)
    items = list(
        cart.items.select_related('product', 'variant', 'product__category')
                  .prefetch_related('product__images')
                  .order_by('id')
    )

    available_items  = [i for i in items if i.is_available]
    unavailable_items = [i for i in items if not i.is_available]

    return render(request, 'cart_detail.html', {
        'cart':              cart,
        'items':             items,
        'available_items':   available_items,
        'unavailable_items': unavailable_items,
        'subtotal':          sum(i.line_total for i in available_items),
        'MAX_QTY':           MAX_QTY_PER_ITEM,
    })




@login_required
@require_POST
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if product.is_blocked or not product.is_listed:
        messages.error(request, 'This product is not available.')
        return redirect(request.META.get('HTTP_REFERER', 'product_shop'))

    variant_id = request.POST.get('variant_id')
    variant    = None
    if variant_id:
        variant = get_object_or_404(ProductVariant, id=variant_id, product=product)

    stock = variant.stock if variant else product.stock
    if stock <= 0:
        messages.error(request, f'"{product.name}" is out of stock.')
        return redirect(request.META.get('HTTP_REFERER', 'product_shop'))

    cart = _get_or_create_cart(request.user)

    try:
        item = CartItem.objects.get(cart=cart, product=product, variant=variant)
        new_qty = item.quantity + 1
        max_qty = min(stock, MAX_QTY_PER_ITEM)

        if item.quantity >= max_qty:
            messages.warning(
                request,
                f'You already have the maximum allowed quantity '
                f'({max_qty}) of "{product.name}" in your cart.'
            )
        else:
            item.quantity = new_qty
            item.save(update_fields=['quantity'])
            messages.success(request, f'"{product.name}" quantity updated to {new_qty}.')

    except CartItem.DoesNotExist:
        CartItem.objects.create(
            cart=cart, product=product, variant=variant, quantity=1
        )
        messages.success(request, f'"{product.name}" added to your cart.')


    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER', 'cart_detail')
    return redirect(next_url)




@login_required
@require_POST
def remove_from_cart(request, item_id):
    item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    name = item.product.name
    item.delete()
    messages.success(request, f'"{name}" removed from your cart.')
    return redirect('cart_detail')



@login_required
@require_POST
def update_cart_item(request, item_id):
    item   = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    action = request.POST.get('action')        
    stock  = item.available_stock
    max_qty = min(stock, MAX_QTY_PER_ITEM)

    if action == 'increment':
        if item.quantity > max_qty:
            messages.warning(
                request,
                f'Maximum quantity ({max_qty}) reached for "{item.product.name}".'
            )
        else:
            item.quantity += 1
            item.save(update_fields=['quantity'])

    elif action == 'decrement':
        if item.quantity <= 1:
            name = item.product.name
            item.delete()
            messages.success(request, f'"{name}" removed from your cart.')
            return redirect('cart_detail')
        else:
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
            messages.warning(
                request,
                f'Quantity capped at {max_qty} for "{item.product.name}" '
                f'(stock: {stock}, max per order: {MAX_QTY_PER_ITEM}).'
            )
            item.quantity = max_qty
        else:
            item.quantity = new_qty

        item.save(update_fields=['quantity'])

    return redirect('cart_detail')




@login_required
@require_POST
def clear_cart(request):
    cart = _get_or_create_cart(request.user)
    cart.items.all().delete()
    messages.success(request, 'Your cart has been cleared.')
    return redirect('cart_detail')