from cart_user.models import Cart, CartItem
from wishlist_user.models import Wishlist


def ensure_session(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def get_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart
    
    cart_id = request.session.get('cart_id')
    if cart_id:
        try:
            return Cart.objects.get(pk=cart_id)
        except Cart.DoesNotExist:
            pass 
    
    cart = Cart.objects.create()
    request.session['cart_id'] = cart.id
    request.session.modified = True  
    return cart


def cart_total_items(cart):
    if not cart:
        return 0
    return sum(item.quantity for item in cart.items.all())


def wishlist_count_for(request):
    if not request.user.is_authenticated:
        return 0
    wl = Wishlist.objects.filter(user=request.user).first()
    return wl.products.count() if wl else 0


def cart_count_payload(request, cart=None):
    cart = cart or get_cart(request)
    return {
        'success': True,
        'total_items': cart_total_items(cart),
        'wishlist_count': wishlist_count_for(request),
    }


def wants_json(request):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.headers.get('Accept', '')
    return 'application/json' in accept
