
from decimal import Decimal
import json

from django.shortcuts import render, redirect, get_object_or_404, reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import transaction as db_tx
from django.conf import settings
from django.http import JsonResponse

# PayPal SDK
from paypalcheckoutsdk.core import PayPalHttpClient, SandboxEnvironment, LiveEnvironment
from paypalcheckoutsdk.orders import OrdersCreateRequest, OrdersCaptureRequest, OrdersGetRequest

from cart_user.models import Cart
from order_user.models import Order, OrderItem
from customers.models import Address
from coupon_admin.models import Coupon, CouponUsage
from wallet_user.models import Wallet, WalletTransaction

# ── Constants ────────────────────────────────────────────────────────────────
FREE_SHIPPING_THRESHOLD = Decimal('999')
SHIPPING_CHARGE         = Decimal('79')
COD_FEE                 = Decimal('0')

COUNTRIES = [
    'India', 'United States', 'United Kingdom',
    'UAE', 'Singapore', 'Canada', 'Australia', 'Other',
]

def _paypal_client():
    if getattr(settings, 'PAYPAL_MODE', 'sandbox') == 'live':
        env = LiveEnvironment(
            client_id=settings.PAYPAL_CLIENT_ID,
            client_secret=settings.PAYPAL_CLIENT_SECRET,
        )
    else:
        env = SandboxEnvironment(
            client_id=settings.PAYPAL_CLIENT_ID,
            client_secret=settings.PAYPAL_CLIENT_SECRET,
        )
    return PayPalHttpClient(env)


def _get_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key
    cart, _ = Cart.objects.get_or_create(session_key=session_key)
    return cart


def _item_price(item):
    return item.variant.price if (item.variant and item.variant.price) else item.product.price


def _calc_totals(subtotal: Decimal, coupon_discount: Decimal = Decimal('0'),
                 wallet_used: Decimal = Decimal('0')) -> dict:
    shipping = SHIPPING_CHARGE if subtotal < FREE_SHIPPING_THRESHOLD else Decimal('0')
    after_coupon = subtotal - coupon_discount
    grand = max(after_coupon + shipping - wallet_used, Decimal('0'))
    return {
        'subtotal': subtotal,
        'shipping': shipping,
        'coupon_discount': coupon_discount,
        'wallet_used': wallet_used,
        'grand_total': grand,
    }




@login_required(login_url='login')
def address_add(request):
    errors, data = {}, {}
    if request.method == 'POST':
        data = request.POST
        for f in ['full_name', 'phone', 'address_line1', 'city', 'state', 'pincode', 'country']:
            if not data.get(f, '').strip():
                errors[f] = 'This field is required.'
        if not errors:
            Address.objects.create(
                user=request.user,
                full_name=data['full_name'].strip(),
                phone=data['phone'].strip(),
                address_line1=data['address_line1'].strip(),
                address_line2=data.get('address_line2', '').strip(),
                city=data['city'].strip(),
                state=data['state'].strip(),
                pincode=data['pincode'].strip(),
                country=data['country'].strip(),
                is_default=bool(data.get('is_default')),
            )
            messages.success(request, 'Address saved.')
            return redirect('checkout')
    return render(request, 'address_form.html', {
        'action': 'add', 'data': data, 'errors': errors,
        'countries': COUNTRIES, 'address': None,
    })


@login_required(login_url='login')
def address_edit(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    errors, data = {}, {}
    if request.method == 'POST':
        data = request.POST
        for f in ['full_name', 'phone', 'address_line1', 'city', 'state', 'pincode', 'country']:
            if not data.get(f, '').strip():
                errors[f] = 'This field is required.'
        if not errors:
            for attr in ['full_name', 'phone', 'address_line1', 'city', 'state', 'pincode', 'country']:
                setattr(address, attr, data[attr].strip())
            address.address_line2 = data.get('address_line2', '').strip()
            address.is_default = bool(data.get('is_default'))
            address.save()
            messages.success(request, 'Address updated.')
            return redirect('checkout')
    return render(request, 'address_form.html', {
        'action': 'edit', 'data': data or {}, 'errors': errors,
        'address': address, 'countries': COUNTRIES,
    })


@require_POST
@login_required(login_url='login')
def address_set_default(request, pk):
    Address.objects.filter(user=request.user, is_default=True).update(is_default=False)
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    addr.is_default = True
    addr.save(update_fields=['is_default'])
    messages.success(request, f'"{addr.full_name}" set as default.')
    return redirect('checkout')


# ─────────────────────────────────────────────────────────────────────────────
#  COUPON VIEWS
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
@login_required(login_url='login')
def apply_coupon(request):
    code = request.POST.get('coupon_code', '').strip().upper()
    if not code:
        messages.error(request, 'Please enter a coupon code.')
        return redirect('checkout')

    # Prevent multiple coupon applications in same session
    if request.session.get('coupon_code'):
        messages.warning(request, 'A coupon is already applied. Remove it first.')
        return redirect('checkout')

    try:
        coupon = Coupon.objects.get(code__iexact=code, is_active=True)
    except Coupon.DoesNotExist:
        messages.error(request, f'"{code}" is not a valid coupon code.')
        return redirect('checkout')

    # Check usage limit
    if coupon.usage_limit and coupon.times_used >= coupon.usage_limit:
        messages.error(request, 'This coupon has reached its usage limit.')
        return redirect('checkout')

    # Check per-user usage
    if CouponUsage.objects.filter(user=request.user, coupon=coupon).exists():
        messages.error(request, 'You have already used this coupon.')
        return redirect('checkout')

    cart = _get_cart(request)
    subtotal = sum(_item_price(i) * i.quantity for i in cart.items.all())

    if coupon.min_order_amount and subtotal < coupon.min_order_amount:
        messages.error(request, f'Minimum order of ₹{coupon.min_order_amount} required for this coupon.')
        return redirect('checkout')

    if coupon.discount_type == 'percentage':
        discount = (subtotal * coupon.discount_value / 100).quantize(Decimal('0.01'))
        if coupon.max_discount_amount:
            discount = min(discount, coupon.max_discount_amount)
    else:
        discount = coupon.discount_value

    request.session['coupon_code']     = coupon.code
    request.session['coupon_discount'] = str(discount)
    messages.success(request, f'Coupon "{coupon.code}" applied — you save ₹{discount:.2f}!')
    return redirect('checkout')


@require_POST
@login_required(login_url='login')
def remove_coupon(request):
    request.session.pop('coupon_code',     None)
    request.session.pop('coupon_discount', None)
    messages.success(request, 'Coupon removed.')
    return redirect('checkout')


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN CHECKOUT VIEW
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='login')
def checkout(request):
    cart       = _get_cart(request)
    cart_items = cart.items.select_related('variant', 'variant__product', 'product').all()

    if not cart_items.exists():
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart_detail')

    subtotal = sum(_item_price(i) * i.quantity for i in cart_items)

    coupon_code     = request.session.get('coupon_code', '')
    coupon_discount = Decimal(request.session.get('coupon_discount', '0'))

    # Re-validate coupon
    if coupon_code:
        try:
            Coupon.objects.get(code=coupon_code, is_active=True)
        except Coupon.DoesNotExist:
            coupon_code = coupon_discount = Decimal('0')
            request.session.pop('coupon_code',     None)
            request.session.pop('coupon_discount', None)

    totals = _calc_totals(subtotal, coupon_discount)

    addresses        = request.user.addresses.all()
    selected_address = addresses.filter(is_default=True).first()
    selected_id      = str(selected_address.id) if selected_address else ''

    # Wallet
    try:
        wallet_balance = Wallet.objects.get(user=request.user).balance
    except Wallet.DoesNotExist:
        wallet_balance = Decimal('0')

    # Enrich cart items for template
    enriched = []
    for item in cart_items:
        enriched.append({
            'product':    item.product,
            'variant':    item.variant,
            'quantity':   item.quantity,
            'unit_price': _item_price(item),
            'line_total': _item_price(item) * item.quantity,
        })

    return render(request, 'checkout.html', {
        'cart_items':       enriched,
        'subtotal':         totals['subtotal'],
        'coupon_code':      coupon_code,
        'coupon_discount':  totals['coupon_discount'],
        'shipping':         totals['shipping'],
        'grand_total':      totals['grand_total'],
        'addresses':        addresses,
        'selected_id':      selected_id,
        'free_threshold':   FREE_SHIPPING_THRESHOLD,
        'wallet_balance':   wallet_balance,
        'cod_fee':          COD_FEE,
        'paypal_client_id': settings.PAYPAL_CLIENT_ID,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  PAYPAL — CREATE ORDER  (called via AJAX from frontend)
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
@login_required(login_url='login')
def paypal_create_order(request):
    """
    Creates a PayPal order and returns the PayPal order ID to the frontend.
    The frontend then opens the PayPal popup using the JS SDK.
    """
    try:
        data           = json.loads(request.body)
        address_id     = data.get('address_id')
        wallet_amount  = Decimal(data.get('wallet_amount', '0'))
        notes          = data.get('notes', '')

        if not address_id:
            return JsonResponse({'error': 'Please select a delivery address.'}, status=400)

        address  = get_object_or_404(Address, pk=address_id, user=request.user)
        cart     = _get_cart(request)
        items    = cart.items.select_related('variant', 'product').all()

        if not items.exists():
            return JsonResponse({'error': 'Cart is empty.'}, status=400)

        subtotal        = sum(_item_price(i) * i.quantity for i in items)
        coupon_code     = request.session.get('coupon_code', '')
        coupon_discount = Decimal(request.session.get('coupon_discount', '0'))

        # Clamp wallet
        try:
            wb = Wallet.objects.get(user=request.user).balance
        except Wallet.DoesNotExist:
            wb = Decimal('0')
        wallet_used = min(wallet_amount, wb)

        totals      = _calc_totals(subtotal, coupon_discount, wallet_used)
        grand_total = totals['grand_total']

        # Store pending-order data in session so capture view can use it
        request.session['pending_checkout'] = {
            'address_id':    str(address_id),
            'wallet_amount': str(wallet_used),
            'notes':         notes,
        }

        # Build PayPal order
        client = _paypal_client()
        pp_req = OrdersCreateRequest()
        pp_req.prefer('return=representation')
        pp_req.request_body({
            'intent': 'CAPTURE',
            'purchase_units': [{
                'amount': {
                    'currency_code': 'USD',           # PayPal needs USD; convert if needed
                    'value': str(grand_total),        # use INR-to-USD conversion in production
                    'breakdown': {
                        'item_total':        {'currency_code': 'USD', 'value': str(subtotal - coupon_discount)},
                        'shipping':          {'currency_code': 'USD', 'value': str(totals['shipping'])},
                        'discount':          {'currency_code': 'USD', 'value': str(coupon_discount)},
                    }
                },
                'description': f'Veska order for {request.user.email}',
            }],
            'application_context': {
                'brand_name':          'Veska',
                'landing_page':        'NO_PREFERENCE',
                'user_action':         'PAY_NOW',
                'shipping_preference': 'NO_SHIPPING',
            }
        })

        response        = client.execute(pp_req)
        paypal_order_id = response.result.id

        # Cache PayPal order ID in session
        request.session['paypal_order_id'] = paypal_order_id

        return JsonResponse({'paypal_order_id': paypal_order_id, 'success': True})

    except Exception as exc:
        import traceback; traceback.print_exc()
        return JsonResponse({'error': str(exc)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
#  PAYPAL — CAPTURE PAYMENT  (called via AJAX after buyer approves)
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
@login_required(login_url='login')
def paypal_capture_order(request):
    """
    Captures the approved PayPal order, then creates the DB Order + OrderItems.
    """
    try:
        data            = json.loads(request.body)
        paypal_order_id = data.get('paypal_order_id')
        payer_id        = data.get('payer_id', '')

        if not paypal_order_id:
            return JsonResponse({'error': 'Missing PayPal order ID.'}, status=400)

        # Capture with PayPal
        client      = _paypal_client()
        capture_req = OrdersCaptureRequest(paypal_order_id)
        capture_res = client.execute(capture_req)

        if capture_res.result.status != 'COMPLETED':
            return JsonResponse({'error': 'PayPal payment not completed.'}, status=400)

        capture_unit   = capture_res.result.purchase_units[0]
        capture_detail = capture_unit.payments.captures[0]
        capture_id     = capture_detail.id

        # Restore pending data from session
        pending        = request.session.get('pending_checkout', {})
        address_id     = pending.get('address_id')
        wallet_amount  = Decimal(pending.get('wallet_amount', '0'))
        notes          = pending.get('notes', '')

        address  = get_object_or_404(Address, pk=address_id, user=request.user)
        cart     = _get_cart(request)
        items    = cart.items.select_related('variant', 'product').all()

        subtotal        = sum(_item_price(i) * i.quantity for i in items)
        coupon_code     = request.session.get('coupon_code', '')
        coupon_discount = Decimal(request.session.get('coupon_discount', '0'))
        coupon_obj      = None
        if coupon_code:
            try:
                coupon_obj = Coupon.objects.get(code=coupon_code, is_active=True)
            except Coupon.DoesNotExist:
                coupon_code = ''; coupon_discount = Decimal('0')

        totals = _calc_totals(subtotal, coupon_discount, wallet_amount)

        with db_tx.atomic():
            order = Order.objects.create(
                user=request.user,
                full_name=address.full_name,
                phone=address.phone,
                address_line1=address.address_line1,
                address_line2=address.address_line2,
                city=address.city,
                state=address.state,
                pincode=address.pincode,
                country=address.country,
                subtotal=totals['subtotal'],
                coupon_code=coupon_code,
                discount_amount=totals['coupon_discount'],
                shipping_charge=totals['shipping'],
                wallet_amount_used=wallet_amount,
                total=totals['grand_total'],
                payment_method='paypal',
                payment_status='paid',
                status='confirmed',
                paypal_order_id=paypal_order_id,
                paypal_capture_id=capture_id,
                paypal_payer_id=payer_id,
                notes=notes,
            )

            for item in items:
                price = _item_price(item)
                img   = item.product.images.first()
                OrderItem.objects.create(
                    order=order,
                    product=item.product,
                    variant=item.variant,
                    product_name=item.product.name,
                    product_slug=item.product.slug,
                    size=item.variant.size if item.variant else '',
                    image_url=img.image.url if (img and img.image) else '',
                    unit_price=price,
                    quantity=item.quantity,
                )
                # Decrement stock
                if item.variant:
                    item.variant.stock = max(0, item.variant.stock - item.quantity)
                    item.variant.save(update_fields=['stock'])
                else:
                    item.product.stock = max(0, item.product.stock - item.quantity)
                    item.product.save(update_fields=['stock'])

            # Coupon usage
            if coupon_obj:
                coupon_obj.times_used += 1
                coupon_obj.save(update_fields=['times_used'])
                CouponUsage.objects.get_or_create(
                    user=request.user, coupon=coupon_obj,
                    defaults={'order': order}
                )

            # Wallet deduction
            if wallet_amount > 0:
                wallet = Wallet.objects.get(user=request.user)
                wallet.balance -= wallet_amount
                wallet.save(update_fields=['balance'])
                WalletTransaction.objects.create(
                    user=request.user,
                    amount=-wallet_amount,
                    transaction_type='DEBIT',
                    order=order,
                    description=f'Payment for order {order.uuid}',
                )

            # Clear cart + session keys
            cart.items.all().delete()
            for key in ('coupon_code', 'coupon_discount', 'pending_checkout', 'paypal_order_id'):
                request.session.pop(key, None)

        return JsonResponse({
            'success':      True,
            'redirect_url': reverse('order_success', kwargs={'uuid': order.uuid}),
        })

    except Exception as exc:
        import traceback; traceback.print_exc()
        return JsonResponse({'error': str(exc)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
#  COD / WALLET PLACE ORDER
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
@login_required(login_url='login')
def place_order_cod_wallet(request):
    """Handles Cash on Delivery and Wallet-only orders (no PayPal)."""
    try:
        data           = json.loads(request.body)
        payment_method = data.get('payment_method', 'cod')   # 'cod' or 'wallet'
        address_id     = data.get('address_id')
        wallet_amount  = Decimal(data.get('wallet_amount', '0'))
        notes          = data.get('notes', '')

        if not address_id:
            return JsonResponse({'error': 'Please select a delivery address.'}, status=400)

        if payment_method not in ('cod', 'wallet'):
            return JsonResponse({'error': 'Invalid payment method.'}, status=400)

        address  = get_object_or_404(Address, pk=address_id, user=request.user)
        cart     = _get_cart(request)
        items    = cart.items.select_related('variant', 'product').all()

        if not items.exists():
            return JsonResponse({'error': 'Cart is empty.'}, status=400)

        subtotal        = sum(_item_price(i) * i.quantity for i in items)
        coupon_code     = request.session.get('coupon_code', '')
        coupon_discount = Decimal(request.session.get('coupon_discount', '0'))
        coupon_obj      = None
        if coupon_code:
            try:
                coupon_obj = Coupon.objects.get(code=coupon_code, is_active=True)
            except Coupon.DoesNotExist:
                coupon_code = ''; coupon_discount = Decimal('0')

        # Wallet validation
        try:
            wb = Wallet.objects.get(user=request.user).balance
        except Wallet.DoesNotExist:
            wb = Decimal('0')
        if payment_method == 'wallet' and wallet_amount > wb:
            return JsonResponse({'error': 'Insufficient wallet balance.'}, status=400)

        wallet_used = min(wallet_amount, wb) if payment_method == 'wallet' else Decimal('0')
        totals      = _calc_totals(subtotal, coupon_discount, wallet_used)

        with db_tx.atomic():
            order = Order.objects.create(
                user=request.user,
                full_name=address.full_name,
                phone=address.phone,
                address_line1=address.address_line1,
                address_line2=address.address_line2,
                city=address.city,
                state=address.state,
                pincode=address.pincode,
                country=address.country,
                subtotal=totals['subtotal'],
                coupon_code=coupon_code,
                discount_amount=totals['coupon_discount'],
                shipping_charge=totals['shipping'],
                wallet_amount_used=wallet_used,
                total=totals['grand_total'],
                payment_method=payment_method,
                payment_status='pending',
                status='confirmed',
                notes=notes,
            )

            for item in items:
                price = _item_price(item)
                img   = item.product.images.first()
                OrderItem.objects.create(
                    order=order,
                    product=item.product,
                    variant=item.variant,
                    product_name=item.product.name,
                    product_slug=item.product.slug,
                    size=item.variant.size if item.variant else '',
                    image_url=img.image.url if (img and img.image) else '',
                    unit_price=price,
                    quantity=item.quantity,
                )
                if item.variant:
                    item.variant.stock = max(0, item.variant.stock - item.quantity)
                    item.variant.save(update_fields=['stock'])
                else:
                    item.product.stock = max(0, item.product.stock - item.quantity)
                    item.product.save(update_fields=['stock'])

            if coupon_obj:
                coupon_obj.times_used += 1
                coupon_obj.save(update_fields=['times_used'])
                CouponUsage.objects.get_or_create(
                    user=request.user, coupon=coupon_obj,
                    defaults={'order': order}
                )

            if wallet_used > 0:
                wallet = Wallet.objects.get(user=request.user)
                wallet.balance -= wallet_used
                wallet.save(update_fields=['balance'])
                WalletTransaction.objects.create(
                    user=request.user,
                    amount=-wallet_used,
                    transaction_type='DEBIT',
                    order=order,
                    description=f'Payment for order {order.uuid}',
                )

            cart.items.all().delete()
            for key in ('coupon_code', 'coupon_discount'):
                request.session.pop(key, None)

        return JsonResponse({
            'success':      True,
            'redirect_url': reverse('order_success', kwargs={'uuid': order.uuid}),
        })

    except Exception as exc:
        import traceback; traceback.print_exc()
        return JsonResponse({'error': str(exc)}, status=500)


@login_required(login_url='login')
def order_success(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)
    return render(request, 'order_success.html', {'order': order})
 
 