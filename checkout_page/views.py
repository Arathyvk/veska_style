import hmac
import hashlib
import json
import razorpay
import datetime
from decimal import Decimal
 
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_tx
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
 
from cart_user.models import Cart
from order_user.models import Order, OrderItem
from customers.models import Address
from coupon_admin.models import Coupon, CouponUsage
from wallet_user.models import Wallet, WalletTransaction
 
FREE_SHIPPING_THRESHOLD = Decimal('999')
SHIPPING_CHARGE         = Decimal('79')
COD_FEE                 = Decimal('0')
 
COUNTRIES = [
    'India', 'United States', 'United Kingdom',
    'UAE', 'Singapore', 'Canada', 'Australia', 'Other',
]
 
 
def _razorpay_client():
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )
 
 
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
 
 
def clear_user_cart(user):
    try:
        cart = Cart.objects.get(user=user)
        cart.items.all().delete()
    except Cart.DoesNotExist:
        pass
 
 
def _item_price(item):
    return item.variant.price if (item.variant and item.variant.price) else item.product.price
 
 
def _calc_totals(subtotal: Decimal, coupon_discount: Decimal = Decimal('0'),
                 wallet_used: Decimal = Decimal('0')) -> dict:
    shipping     = SHIPPING_CHARGE if subtotal < FREE_SHIPPING_THRESHOLD else Decimal('0')
    after_coupon = subtotal - coupon_discount
    grand        = max(after_coupon + shipping - wallet_used, Decimal('0'))
    return {
        'subtotal':        subtotal,
        'shipping':        shipping,
        'coupon_discount': coupon_discount,
        'wallet_used':     wallet_used,
        'grand_total':     grand,
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
            address.is_default    = bool(data.get('is_default'))
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
 
 

 
@require_POST
@login_required(login_url='login')
def apply_coupon(request):
    code = request.POST.get('coupon_code', '').strip().upper()
    if not code:
        messages.error(request, 'Please enter a coupon code.')
        return redirect('checkout')
 
    if request.session.get('coupon_code'):
        messages.warning(request, 'A coupon is already applied. Remove it first.')
        return redirect('checkout')
 
    try:
        coupon = Coupon.objects.get(code__iexact=code, is_active=True)
    except Coupon.DoesNotExist:
        messages.error(request, f'"{code}" is not a valid coupon code.')
        return redirect('checkout')
 
    if coupon.usage_limit and coupon.times_used >= coupon.usage_limit:
        messages.error(request, 'This coupon has reached its usage limit.')
        return redirect('checkout')
 
    if CouponUsage.objects.filter(user=request.user, coupon=coupon).exists():
        messages.error(request, 'You have already used this coupon.')
        return redirect('checkout')
 
    cart     = _get_cart(request)
    subtotal = sum(_item_price(i) * i.quantity for i in cart.items.all())
 
    if coupon.min_order_amount and subtotal < coupon.min_order_amount:
        messages.error(request,
            f'Minimum order of ₹{coupon.min_order_amount} required for this coupon.')
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
 
 

 
@login_required(login_url='login')
def checkout(request):
    cart       = _get_cart(request)
    cart_items = cart.items.select_related('variant', 'variant__product', 'product').all()
 
    if not cart_items.exists():
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart_detail')
 
    subtotal        = sum(_item_price(i) * i.quantity for i in cart_items)
    coupon_code     = request.session.get('coupon_code', '')
    coupon_discount = Decimal(request.session.get('coupon_discount', '0'))
 
    if coupon_code:
        try:
            Coupon.objects.get(code=coupon_code, is_active=True)
        except Coupon.DoesNotExist:
            coupon_code     = ''
            coupon_discount = Decimal('0')
            request.session.pop('coupon_code',     None)
            request.session.pop('coupon_discount', None)
 
    totals    = _calc_totals(subtotal, coupon_discount)
    addresses = request.user.addresses.all()
    selected  = addresses.filter(is_default=True).first()
 
    try:
        wallet_balance = Wallet.objects.get(user=request.user).balance
    except Wallet.DoesNotExist:
        wallet_balance = Decimal('0')
 
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
        'cart_items':      enriched,
        'subtotal':        totals['subtotal'],
        'coupon_code':     coupon_code,
        'coupon_discount': totals['coupon_discount'],
        'shipping':        totals['shipping'],
        'grand_total':     totals['grand_total'],
        'addresses':       addresses,
        'selected_id':     str(selected.id) if selected else '',
        'free_threshold':  FREE_SHIPPING_THRESHOLD,
        'wallet_balance':  wallet_balance,
        'cod_fee':         COD_FEE,
        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
    })
 
 
 
@require_POST
@login_required(login_url='login')
def razorpay_create_order(request):
    try:
        data          = json.loads(request.body)
        address_id    = data.get('address_id')
        wallet_amount = Decimal(str(data.get('wallet_amount', '0')))
        notes         = data.get('notes', '')
 
        if not address_id:
            return JsonResponse({'error': 'Please select a delivery address.'}, status=400)
 
        get_object_or_404(Address, pk=address_id, user=request.user)
 
        cart  = _get_cart(request)
        items = cart.items.select_related('variant', 'product').all()
 
        if not items.exists():
            return JsonResponse({'error': 'Cart is empty.'}, status=400)
 
        subtotal        = sum(_item_price(i) * i.quantity for i in items)
        coupon_code     = request.session.get('coupon_code', '')
        coupon_discount = Decimal(request.session.get('coupon_discount', '0'))
 
        try:
            wb = Wallet.objects.get(user=request.user).balance
        except Wallet.DoesNotExist:
            wb = Decimal('0')
 
        wallet_used = min(wallet_amount, wb, subtotal)
        totals      = _calc_totals(subtotal, coupon_discount, wallet_used)
        grand_total = totals['grand_total']
 
        request.session['pending_checkout'] = {
            'address_id':    str(address_id),
            'wallet_amount': str(wallet_used),
            'notes':         notes,
        }
 
        amount_paise = int(grand_total * 100)
 
        client   = _razorpay_client()
        rz_order = client.order.create({
            'amount':          amount_paise,
            'currency':        'INR',
            'payment_capture': 1,
            'notes': {
                'user_email': request.user.email,
                'address_id': str(address_id),
            },
        })
 
        request.session['razorpay_order_id'] = rz_order['id']
 
        return JsonResponse({
            'success':           True,
            'razorpay_order_id': rz_order['id'],
            'amount':            amount_paise,
            'currency':          'INR',
            'key_id':            settings.RAZORPAY_KEY_ID,
            'prefill': {
                'name': (
                    f"{getattr(request.user, 'first_name', '')} "
                    f"{getattr(request.user, 'last_name', '')}"
                ).strip() or request.user.username or request.user.email,
                'email': request.user.email,
            },
        })
 
    except Exception as exc:
        import traceback; traceback.print_exc()
        return JsonResponse({'error': str(exc)}, status=500)
 
 

@require_POST
@login_required(login_url='login')
def razorpay_verify_payment(request):
    try:
        data               = json.loads(request.body)
        rz_order_id        = data.get('razorpay_order_id', '')
        rz_payment_id      = data.get('razorpay_payment_id', '')
        rz_signature       = data.get('razorpay_signature', '')
 
        if not all([rz_order_id, rz_payment_id, rz_signature]):
            return JsonResponse({'success': False, 'error': 'Incomplete payment details.'}, status=400)
 
        body     = f"{rz_order_id}|{rz_payment_id}"
        expected = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()
 
        if not hmac.compare_digest(expected, rz_signature):
            return JsonResponse({'success': False, 'error': 'Payment verification failed.'}, status=400)
 
        pending       = request.session.get('pending_checkout', {})
        address_id    = pending.get('address_id')
        wallet_amount = Decimal(pending.get('wallet_amount', '0'))
        notes         = pending.get('notes', '')
 
        if not address_id:
            return JsonResponse({'success': False, 'error': 'Session expired. Please retry.'}, status=400)
 
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
                coupon_code     = ''
                coupon_discount = Decimal('0')
 
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
                payment_method='razorpay',
                payment_status='paid',
                status='confirmed',
                razorpay_order_id=rz_order_id,
                razorpay_payment_id=rz_payment_id,
                razorpay_signature=rz_signature,
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
 
            if wallet_amount > 0:
                wallet          = Wallet.objects.get(user=request.user)
                wallet.balance -= wallet_amount
                wallet.save(update_fields=['balance'])
                WalletTransaction.objects.create(
                    user=request.user,
                    amount=-wallet_amount,
                    transaction_type='DEBIT',
                    order=order,
                    description=f'Payment for order {order.uuid}',
                )
 
            clear_user_cart(request.user)
            for key in ('coupon_code', 'coupon_discount', 'pending_checkout', 'razorpay_order_id'):
                request.session.pop(key, None)
 
        return JsonResponse({
            'success':      True,
            'redirect_url': reverse('order_success', kwargs={'uuid': order.uuid}),
        })
 
    except Exception as exc:
        import traceback; traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)
 
 

 
@require_POST
@login_required(login_url='login')
def place_order(request):
    try:
        data           = json.loads(request.body)
        payment_method = data.get('payment_method', 'cod')
        address_id     = data.get('address_id')
        wallet_amount  = Decimal(str(data.get('wallet_amount', '0')))
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
                coupon_code     = ''
                coupon_discount = Decimal('0')
 
        try:
            wb = Wallet.objects.get(user=request.user).balance
        except Wallet.DoesNotExist:
            wb = Decimal('0')
 
        if payment_method == 'wallet':
            if wallet_amount <= 0:
                return JsonResponse({'error': 'Enter a wallet amount greater than zero.'}, status=400)
            if wallet_amount > wb:
                return JsonResponse({'error': 'Insufficient wallet balance.'}, status=400)
            wallet_used = min(wallet_amount, wb)
        else:
            wallet_used = Decimal('0')
 
        totals = _calc_totals(subtotal, coupon_discount, wallet_used)
 
        if payment_method == 'wallet' and totals['grand_total'] > 0:
            return JsonResponse({
                'error': (
                    f'Wallet balance insufficient to cover the full order. '
                    f'Remaining: ₹{totals["grand_total"]}. '
                    f'Please use Razorpay for the remaining amount.'
                )
            }, status=400)
 
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
                wallet          = Wallet.objects.get(user=request.user)
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
            'order_uuid':   str(order.uuid),
            'redirect_url': reverse('order_success', kwargs={'uuid': order.uuid}),
        })
 
    except Exception as exc:
        import traceback; traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)
 
 

@login_required(login_url='login')
def order_success(request, uuid):
    order     = get_object_or_404(Order, uuid=uuid, user=request.user)
    estimated = order.created_at + datetime.timedelta(days=5)
    return render(request, 'order_success.html', {
        'order':              order,
        'estimated_delivery': estimated.strftime('%d %b %Y'),
    })
 
 

 
@login_required(login_url='login')
def payment_failure(request):
    pending           = request.session.get('pending_checkout', {})
    session_rz_id     = request.session.get('razorpay_order_id', '')
    get_rz_id         = request.GET.get('razorpay_order_id', '')
    get_uuid          = request.GET.get('uuid', '')
 
    razorpay_order_id = session_rz_id or get_rz_id
 
    order  = None
    amount = None
 
    if razorpay_order_id:
        order = Order.objects.filter(
            razorpay_order_id=razorpay_order_id,
            user=request.user,
        ).first()
 
    if not order and get_uuid:
        try:
            order = Order.objects.get(uuid=get_uuid, user=request.user)
        except Order.DoesNotExist:
            pass
 
    if order:
        amount            = order.total
        razorpay_order_id = razorpay_order_id or getattr(order, 'razorpay_order_id', '')
    else:
        try:
            cart     = Cart.objects.get(user=request.user)
            items    = cart.items.select_related('variant', 'product').all()
            subtotal = sum(_item_price(i) * i.quantity for i in items)
            coupon_discount = Decimal(request.session.get('coupon_discount', '0'))
            wallet_used     = Decimal(pending.get('wallet_amount', '0'))
            totals          = _calc_totals(subtotal, coupon_discount, wallet_used)
            amount          = totals['grand_total']
        except Exception:
            amount = None
 
    return render(request, 'payment_failure.html', {
        'order':             order,
        'grand_total':       amount,
        'razorpay_order_id': razorpay_order_id,
        'error_reason':      request.GET.get('reason',
                             request.GET.get('error_description',
                             'Payment was declined by the bank')),
        'error_code':        request.GET.get('error_code', 'PAYMENT_FAILED'),
        'failed_at':         timezone.now().strftime('%d %b %Y, %I:%M %p'),
    })
 