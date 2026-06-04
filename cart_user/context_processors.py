from cart_user.cart_helpers import get_cart, cart_total_items, wishlist_count_for


def cart_nav_counts(request):
    try:
        cart = get_cart(request)
        total = cart_total_items(cart)
    except Exception:
        total = 0
    return {
        'cart_nav_count': total,
        'wishlist_nav_count': wishlist_count_for(request),
    }
