from decimal import Decimal
from django.utils import timezone
from cart_user.models import Cart
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from .models import Order, OrderItem, Coupon
from customers.models import Address


FREE_SHIPPING_THRESHOLD = Decimal('999')
SHIPPING_CHARGE         = Decimal('79')

COUNTRIES = [
    "India", "United States", "United Kingdom",
    "UAE", "Singapore", "Other",
]




def _get_addresses(request):
    if request.user.is_authenticated:
        return Address.objects.filter(user=request.user)
    return Address.objects.none()


def _get_cart(request):
    if not request.session.session_key:
        request.session.create()
    cart, _ = Cart.objects.get_or_create(session_key=request.session.session_key)
    return cart


def _calc_totals(subtotal: Decimal, coupon=None):
    discount_amount = coupon.calculate_discount(subtotal) if coupon else Decimal('0')
    discounted      = subtotal - discount_amount
    shipping        = SHIPPING_CHARGE if discounted < FREE_SHIPPING_THRESHOLD else Decimal('0')
    total           = discounted + shipping
    return {
        'discount_amount': discount_amount,
        'shipping':        shipping,
        'total':           total,
    }


def _get_session_coupon(request):
    code = request.session.get('coupon_code')
    if not code:
        return None
    try:
        return Coupon.objects.get(code__iexact=code, is_active=True)
    except Coupon.DoesNotExist:
        request.session.pop('coupon_code', None)
        return None




@login_required
def address_add(request):
    errors = {}
    data   = {}

    if request.method == 'POST':
        data     = request.POST
        required = ['full_name', 'phone', 'address_line1', 'city', 'state', 'pincode', 'country']

        for f in required:
            if not data.get(f, '').strip():
                errors[f] = 'This field is required.'

        if not errors:
            Address.objects.create(
                user          = request.user,
                full_name     = data['full_name'].strip(),
                phone         = data['phone'].strip(),
                address_line1 = data['address_line1'].strip(),
                address_line2 = data.get('address_line2', '').strip(),
                city          = data['city'].strip(),
                state         = data['state'].strip(),
                pincode       = data['pincode'].strip(),
                country       = data.get('country', 'India').strip(),
                is_default    = bool(data.get('is_default')),
            )
            messages.success(request, 'Address saved!')
            return redirect('checkout')

    return render(request, 'address_form.html', {
        'action':    'add',
        'data':      data,
        'errors':    errors,
        'countries': COUNTRIES,
        'address':   None,
    })


@login_required
def address_edit(request, pk):
    address = get_object_or_404(Address, id=pk, user=request.user)
    errors  = {}
    data    = {}

    if request.method == 'POST':
        data     = request.POST
        required = ['full_name', 'phone', 'address_line1', 'city', 'state', 'pincode', 'country']

        for f in required:
            if not data.get(f, '').strip():
                errors[f] = 'This field is required.'

        if not errors:
            address.full_name     = data['full_name'].strip()
            address.phone         = data['phone'].strip()
            address.address_line1 = data['address_line1'].strip()
            address.address_line2 = data.get('address_line2', '').strip()
            address.city          = data['city'].strip()
            address.state         = data['state'].strip()
            address.pincode       = data['pincode'].strip()
            address.country       = data.get('country', 'India').strip()
            address.is_default    = bool(data.get('is_default'))
            address.save()

            messages.success(request, 'Address updated!')
            return redirect('checkout')

    return render(request, 'address_form.html', {
        'action':    'edit',
        'data':      data,
        'errors':    errors,
        'address':   address,
        'countries': COUNTRIES,
    })


@require_POST
@login_required
def address_set_default(request, pk):
    Address.objects.filter(user=request.user, is_default=True).update(is_default=False)
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    addr.is_default = True
    addr.save()
    return redirect('checkout')




@require_POST
def apply_coupon(request):
    code = request.POST.get('coupon_code', '').strip().upper()

    if not code:
        messages.error(request, 'Please enter a coupon code.')
        return redirect('checkout')

    try:
        coupon = Coupon.objects.get(code__iexact=code)
    except Coupon.DoesNotExist:
        messages.error(request, f'"{code}" is not a valid coupon code.')
        return redirect('checkout')

    valid, reason = coupon.is_valid()
    if not valid:
        messages.error(request, reason)
        return redirect('checkout')

    cart     = _get_cart(request)
    subtotal = Decimal(str(cart.subtotal))
    if subtotal < coupon.min_order_value:
        messages.error(
            request,
            f'This coupon requires a minimum order of ₹{coupon.min_order_value:.0f}.'
        )
        return redirect('checkout')

    request.session['coupon_code'] = coupon.code
    discount = coupon.calculate_discount(subtotal)
    messages.success(request, f'Coupon "{coupon.code}" applied! You save ₹{discount:.2f}.')
    return redirect('checkout')


@require_POST
def remove_coupon(request):
    request.session.pop('coupon_code', None)
    messages.success(request, 'Coupon removed.')
    return redirect('checkout')



def checkout(request):
    cart  = _get_cart(request)
    items = list(cart.items)

    if cart.is_empty:
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart_detail')

    blocked = [i for i in items if not i.is_available]
    if blocked:
        messages.error(request, 'Remove unavailable items from your cart before checkout.')
        return redirect('cart_detail')

    subtotal = Decimal(str(cart.subtotal))
    coupon   = _get_session_coupon(request)
    totals   = _calc_totals(subtotal, coupon)

    addresses        = list(_get_addresses(request))
    default_addr     = next((a for a in addresses if a.is_default), None) or (addresses[0] if addresses else None)
    selected_addr_id = request.GET.get('addr') or (str(default_addr.pk) if default_addr else '')

    return render(request, 'checkout.html', {
        'cart':             cart,
        'items':            items,
        'addresses':        addresses,
        'selected_addr_id': selected_addr_id,
        'default_addr':     default_addr,
        'subtotal':         subtotal,
        'coupon':           coupon,
        'discount_amount':  totals['discount_amount'],
        'shipping':         totals['shipping'],
        'tax_rate_pct':     0,
        'tax':              Decimal('0'),
        'total':            totals['total'],
        'free_threshold':   FREE_SHIPPING_THRESHOLD,
    })




@require_POST
def place_order(request):
    if not request.user.is_authenticated:
        messages.error(request, 'You must be logged in to place an order.')
        return redirect('login')

    cart  = _get_cart(request)
    items = list(cart.items)

    if cart.is_empty:
        messages.error(request, 'Your cart is empty.')
        return redirect('cart_detail')

    blocked = [i for i in items if not i.is_available]
    if blocked:
        messages.error(request, 'Remove unavailable items before placing your order.')
        return redirect('cart_detail')

    addr_id = request.POST.get('address_id')
    if not addr_id:
        messages.error(request, 'Please select a delivery address.')
        return redirect('checkout')

    addr = get_object_or_404(Address, pk=addr_id, user=request.user)

    subtotal = Decimal(str(cart.subtotal))
    coupon   = _get_session_coupon(request)

    if coupon:
        valid, reason = coupon.is_valid()
        if not valid:
            request.session.pop('coupon_code', None)
            messages.error(request, f'Coupon no longer valid: {reason}')
            return redirect('checkout')

    totals = _calc_totals(subtotal, coupon)

    order = Order.objects.create(
        user            = request.user,
        session_key     = request.session.session_key,
        full_name       = addr.full_name,
        phone           = addr.phone,
        address_line1   = addr.address_line1,
        address_line2   = addr.address_line2,
        city            = addr.city,
        state           = addr.state,
        pincode         = addr.pincode,
        country         = addr.country,
        subtotal        = subtotal,
        coupon_code     = coupon.code if coupon else '',
        discount_type   = coupon.discount_type if coupon else '',
        discount_value  = coupon.value if coupon else Decimal('0'),
        discount_amount = totals['discount_amount'],
        shipping_charge = totals['shipping'],
        tax             = Decimal('0'),
        total           = totals['total'],
        payment_method  = 'cod',
        status          = 'confirmed',
        notes           = request.POST.get('notes', '').strip(),
    )

    for item in items:
        img = item.product.primary_image
        OrderItem.objects.create(
            order        = order,
            product      = item.product,
            product_name = item.product.name,
            product_slug = item.product.slug,
            size         = item.variant.size if item.variant else '',
            image_url    = img.image.url if img else '',
            unit_price   = item.unit_price,
            quantity     = item.quantity,
            line_total   = item.line_total,
        )
        if item.variant:
            item.variant.stock = max(0, item.variant.stock - item.quantity)
            item.variant.save(update_fields=['stock'])
        else:
            item.product.stock = max(0, item.product.stock - item.quantity)
            item.product.save(update_fields=['stock'])

    if coupon:
        coupon.times_used += 1
        coupon.save(update_fields=['times_used'])
        request.session.pop('coupon_code', None)

    cart.cart_items.all().delete()
    return redirect('order_success', order_number=order.order_number)




def order_success(request, order_number):
    if request.user.is_authenticated:
        order = get_object_or_404(Order, order_number=order_number, user=request.user)
    else:
        order = get_object_or_404(
            Order,
            order_number=order_number,
            session_key=request.session.session_key,
        )
    return render(request, 'order_success.html', {'order': order})



@login_required
def order_detail(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    return render(request, 'order_detail.html', {'order': order})