import json
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from cart_user.models import Cart, CartItem
from wishlist_user.models import Wishlist, WishlistProduct
from product_admin.models import Product, ProductVariant


def _get_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart
    request.session.save()
    cart, _ = Cart.objects.get_or_create(user=None)
    return cart


def _get_wishlist(request):
    if request.user.is_authenticated:
        wl, _ = Wishlist.objects.get_or_create(user=request.user)
        return wl
    return None


def _wishlist_ids(request):
   
    if not request.user.is_authenticated:
        return []
    
    try:
        wishlist_ids = list(
            WishlistProduct.objects.filter(
                wishlist__user=request.user
            ).values_list('product__uuid', flat=True)
        )
        result = [str(uid) for uid in wishlist_ids]
        
        return result
    except Exception as e:
        return []
    

@require_POST
def wishlist_toggle(request, slug):
    
    if not request.user.is_authenticated:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': 'Please login first',
                'redirect_url': '/login/?next=' + request.path
            }, status=401)
        messages.info(request, 'Please log in to save items to your wishlist.')
        return redirect('login')

    product = get_object_or_404(Product, slug=slug, is_active=True)
    wl, _ = Wishlist.objects.get_or_create(user=request.user)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        payload = {}
    selected_size = payload.get('size') or None
    selected_color = payload.get('color') or None

    color_variants_exist = product.variants.filter(color__isnull=False).exclude(color='').exists()
    if product.variants.exists():
        if not selected_size or (color_variants_exist and not selected_color):
            return JsonResponse({
                'success': False,
                'error': 'Please select a valid size and color combination before saving.',
            }, status=400)

        if not ProductVariant.objects.filter(
            product=product, size=selected_size, color=selected_color
        ).exists():
            return JsonResponse({
                'success': False,
                'error': 'The selected color and size combination is not available.',
            }, status=400)

    existing = WishlistProduct.objects.filter(
        wishlist=wl, 
        product=product, 
        selected_size=selected_size,
        color=selected_color
    ).first()

    if existing:
        existing.delete()
        is_wishlisted = False
        message = f'"{product.name}" removed from wishlist.'
    else:
        WishlistProduct.objects.create(
            wishlist=wl, 
            product=product, 
            selected_size=selected_size,
            color=selected_color
        )
        is_wishlisted = True
        message = f'"{product.name}" saved to wishlist!'

    wishlist_count = wl.items.count()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'is_wishlisted': is_wishlisted,
            'wishlist_count': wishlist_count,
            'message': message,
            'product_uuid': str(product.uuid), 
            'product_slug': product.slug,
        })

    messages.success(request, message) if is_wishlisted else messages.info(request, message)
    next_url = request.POST.get('next', 'wishlist_detail')
    return redirect(next_url)


@login_required(login_url='login')
def wishlist_detail(request):
    wl, _ = Wishlist.objects.get_or_create(user=request.user)
    wishlist_products = list(
        wl.items.filter(product__is_active=True)
                .select_related('product')
                .prefetch_related('product__variants')
    )

    for item in wishlist_products:
        item.matched_variant = item.product.variants.filter(
            size=item.selected_size,
            color=item.color
        ).first()
        variant_price = item.matched_variant.price if item.matched_variant else item.product.price
        item.best_offer = item.product.get_best_offer(amount=variant_price)
        if item.best_offer:
            item.offer_discount = item.best_offer.calculate_discount(variant_price)
            item.discounted_price = variant_price - item.offer_discount
        else:
            item.offer_discount = Decimal('0')
            item.discounted_price = variant_price

    cart = _get_cart(request)
    cart_product_uuids = set(
        str(item.product.uuid) for item in cart.items.select_related('product')
    ) if cart else set()

    return render(request, 'wishlist.html', {
        'wishlist_products': wishlist_products,
        'cart_product_uuids': cart_product_uuids,
    })

@login_required
def remove_wishlist_item(request, slug):
    product = get_object_or_404(Product, slug=slug)
    wl = get_object_or_404(Wishlist, user=request.user)

    WishlistProduct.objects.filter(wishlist=wl, product=product).delete()
    count = wl.items.count()

    return JsonResponse({
        'success': True,
        'message': 'Removed from wishlist',
        'wishlist_count': count,
        'product_uuid': str(product.uuid),
        'product_slug': slug,
    })


@login_required
def move_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    wl = get_object_or_404(Wishlist, user=request.user)

    wishlist_item = WishlistProduct.objects.filter(wishlist=wl, product=product).first()

    variant = None
    if wishlist_item:
        variant = ProductVariant.objects.filter(
            product=product,
            size=wishlist_item.selected_size,
            color=wishlist_item.color
        ).first()

    cart = _get_cart(request)

    cart_item, created = CartItem.objects.get_or_create(
        cart=cart, product=product, variant=variant,
        defaults={'quantity': 1}
    )
    if not created:
        cart_item.quantity += 1
        cart_item.save()

    if wishlist_item:
        wishlist_item.delete()

    messages.success(request, f'{product.name} moved to cart')
    return redirect('cart_detail')


@login_required
def wishlist_count(request):
    wl, _ = Wishlist.objects.get_or_create(user=request.user)
    return JsonResponse({
        'success': True, 
        'count': wl.items.count()
    })