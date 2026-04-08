from django.shortcuts import render, redirect, get_object_or_404
from django.http      import JsonResponse
from django.contrib   import messages
from django.views.decorators.http import require_POST

from product_admin.models import Product, ProductVariant, ProductReview
from cart_user.models     import Cart, CartItem, Wishlist, MAX_QTY_PER_ITEM



def _get_cart(request):
    if not request.session.session_key:
        request.session.create()
    cart, _ = Cart.objects.get_or_create(session_key=request.session.session_key)
    return cart


def _get_wishlist(request):
    if not request.session.session_key:
        request.session.create()
    wl, _ = Wishlist.objects.get_or_create(session_key=request.session.session_key)
    return wl


def _cart_subtotal(cart):
    items = CartItem.objects.filter(cart=cart).select_related('product')
    return sum(float(ci.product.price) * ci.quantity for ci in items)


def _is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _wishlist_ids(request):
    """Set of product PKs in the session wishlist — used by templates."""
    return set(_get_wishlist(request).products.values_list('pk', flat=True))


def _cart_ids(request):
    """Set of product PKs in the session cart — used by templates."""
    return set(_get_cart(request).cart_items.values_list('product_id', flat=True))




@require_POST
def submit_review(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)

    author = request.POST.get('author_name', '').strip() or 'Anonymous'
    body   = request.POST.get('body', '').strip()

    try:
        rating = int(request.POST.get('rating', 0))
        assert 1 <= rating <= 5
    except (ValueError, TypeError, AssertionError):
        messages.error(request, 'Please select a rating between 1 and 5.')
        return redirect('product_detail', slug=slug)

    if not body:
        messages.error(request, 'Review text cannot be empty.')
        return redirect('product_detail', slug=slug)

    ProductReview.objects.create(
        product=product, author_name=author,
        rating=rating, body=body, is_approved=False,
    )
    messages.success(request, 'Thank you! Your review will appear after moderation.')
    return redirect('product_detail', slug=slug)




@require_POST
def cart_add(request, slug):
    ajax = _is_ajax(request)

    try:
        product = (
            Product.objects
            .prefetch_related('variants')
            .get(slug=slug, is_active=True)
        )
    except Product.DoesNotExist:
        if ajax:
            return JsonResponse({'ok': False, 'msg': 'Product is not available.'}, status=404)
        messages.error(request, 'This product is not available.')
        return redirect('product_shop')

    size    = request.POST.get('size', '').strip()
    variant = None
    if size:
        try:
            variant = product.variants.get(size=size)
        except ProductVariant.DoesNotExist:
            if ajax:
                return JsonResponse({'ok': False, 'msg': 'Selected size not found.'}, status=400)
            messages.error(request, 'Selected size is not available.')
            return redirect('product_detail', slug=slug)

    available = variant.stock if variant else product.total_stock
    if available == 0:
        if ajax:
            return JsonResponse({'ok': False, 'msg': 'This item is out of stock.'}, status=400)
        messages.error(request, 'Sorry, this item is out of stock.')
        return redirect('product_detail', slug=slug)

    try:
        qty = max(1, int(request.POST.get('quantity', 1)))
    except (ValueError, TypeError):
        qty = 1

    cart = _get_cart(request)
    item, created = CartItem.objects.get_or_create(
        cart=cart, product=product, variant=variant,
        defaults={'quantity': 0},
    )
    new_qty       = item.quantity + qty
    capped        = min(new_qty, available, MAX_QTY_PER_ITEM)
    item.quantity = capped
    item.save()

    _get_wishlist(request).products.remove(product)

    msg = (
        f'"{product.name}" added to cart!'
        if created else
        f'Cart updated — {capped} in bag.'
    )
    if capped < new_qty:
        msg += f' (Max {MAX_QTY_PER_ITEM} per item.)'

    if ajax:
        return JsonResponse({
            'ok':         True,
            'msg':        msg,
            'cart_count': cart.total_items,
            'item_qty':   capped,
        })
    messages.success(request, msg)
    return redirect(request.POST.get('next', 'cart_detail'))




@require_POST
def cart_update(request, item_id):
    ajax = _is_ajax(request)
    cart = _get_cart(request)

    try:
        item = (
            CartItem.objects
            .select_related('product', 'variant')
            .get(pk=item_id, cart=cart)
        )
    except CartItem.DoesNotExist:
        if ajax:
            return JsonResponse({'ok': False, 'msg': 'Item not found.'}, status=404)
        return redirect('cart_detail')

    action = request.POST.get('action', '')
    if action == 'inc':
        new_qty = item.quantity + 1
    elif action == 'dec':
        new_qty = item.quantity - 1
    elif action == 'set':
        try:
            new_qty = int(request.POST.get('quantity', item.quantity))
        except (ValueError, TypeError):
            new_qty = item.quantity
    else:
        new_qty = item.quantity

    if new_qty <= 0:
        item.delete()
        if ajax:
            return JsonResponse({
                'ok': True, 'removed': True,
                'cart_count': cart.total_items,
                'subtotal':   f'{_cart_subtotal(cart):.2f}',
            })
        messages.info(request, 'Item removed from cart.')
        return redirect('cart_detail')

    capped        = min(new_qty, item.available_stock, MAX_QTY_PER_ITEM)
    item.quantity = capped
    item.save()

    subtotal   = _cart_subtotal(cart)
    line_total = float(item.product.price) * capped
    cart_count = sum(CartItem.objects.filter(cart=cart).values_list('quantity', flat=True))

    if ajax:
        return JsonResponse({
            'ok':         True,
            'removed':    False,
            'item_qty':   capped,
            'line_total': f'{line_total:.2f}',
            'cart_count': cart_count,
            'subtotal':   f'{subtotal:.2f}',
            'capped':     capped < new_qty,
        })
    return redirect('cart_detail')




@require_POST
def cart_remove(request, item_id):
    cart = _get_cart(request)
    CartItem.objects.filter(pk=item_id, cart=cart).delete()

    ajax = _is_ajax(request)
    if ajax:
        subtotal   = _cart_subtotal(cart)
        cart_count = sum(CartItem.objects.filter(cart=cart).values_list('quantity', flat=True))
        return JsonResponse({'ok': True, 'cart_count': cart_count, 'subtotal': f'{subtotal:.2f}'})
    messages.info(request, 'Item removed from cart.')
    return redirect('cart_detail')



def cart_detail(request):
    FREE_SHIPPING = 999
    SHIPPING_FEE  = 79

    cart  = _get_cart(request)
    items = list(cart.items)

    blocked_items = [i for i in items if not i.is_available]
    ok_items      = [i for i in items if     i.is_available]
    can_checkout  = bool(ok_items) and not blocked_items

    subtotal       = cart.subtotal
    shipping       = 0 if subtotal >= FREE_SHIPPING else SHIPPING_FEE
    order_total    = subtotal + shipping
    remaining_free = max(0, FREE_SHIPPING - subtotal)

    return render(request, 'cart.html', {
        'cart':           cart,
        'items':          items,
        'blocked_items':  blocked_items,
        'ok_items':       ok_items,
        'can_checkout':   can_checkout,
        'subtotal':       subtotal,
        'shipping':       shipping,
        'order_total':    order_total,
        'remaining_free': remaining_free,
        'max_qty':        MAX_QTY_PER_ITEM,
        'cart_count':     cart.total_items,
    })




@require_POST
def wishlist_toggle(request, slug):

    try:
        product = Product.objects.get(slug=slug, is_active=True)
    except Product.DoesNotExist:
        if ajax:
            return JsonResponse({'ok': False, 'msg': 'Product not found.'}, status=404)
        return redirect('product_shop')

    wl = _get_wishlist(request)

    if wl.products.filter(pk=product.pk).exists():
        wl.products.remove(product)
        added = False
        msg   = f'"{product.name}" removed from wishlist.'
    else:
        wl.products.add(product)
        added = True
        msg   = f'"{product.name}" saved to wishlist!'

   

    messages.success(request, msg)
    return redirect(request.POST.get('next', 'product_shop'))




def wishlist_detail(request):
    wl       = _get_wishlist(request)
    products = wl.products.filter(is_active=True).prefetch_related('images', 'variants')
    cart     = _get_cart(request)

    return render(request, 'wishlist.html', {
        'products':         products,
        'cart_product_ids': _cart_ids(request),    
        'cart_count':       cart.total_items,
        'wishlist_count':   wl.products.count(),
    })



def product_shop(request):
    from django.core.paginator import Paginator
    from django.db.models      import Q

    query    = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    sort     = request.GET.get('sort', 'newest')

    qs = Product.objects.filter(is_active=True).prefetch_related('images', 'variants')

    if query:
        qs = qs.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__icontains=query)
        )
    if category:
        qs = qs.filter(category=category)

    sort_map = {
        'newest':     '-created_at',
        'oldest':     'created_at',
        'price_asc':  'price',
        'price_desc': '-price',
    }
    qs = qs.order_by(sort_map.get(sort, '-created_at'))

    paginator = Paginator(qs, 12)
    page      = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'product_shop.html', {
        'products':             page,
        'query':                query,
        'category':             category,
        'sort':                 sort,
        'wishlist_product_ids': _wishlist_ids(request),
        'cart_product_ids':     _cart_ids(request),
        'cart_count':           _get_cart(request).total_items,
        'wishlist_count':       _get_wishlist(request).products.count(),
    })




def product_detail(request, slug):
    product  = get_object_or_404(Product, slug=slug, is_active=True)
    reviews  = product.reviews.filter(is_approved=True)
    variants = product.variants.all()

    return render(request, 'product_detail.html', {
        'product':              product,
        'reviews':              reviews,
        'variants':             variants,
        'wishlist_product_ids': _wishlist_ids(request),
        'cart_product_ids':     _cart_ids(request),
        'cart_count':           _get_cart(request).total_items,
        'wishlist_count':       _get_wishlist(request).products.count(),
    })