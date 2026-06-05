import json
import datetime
from decimal import Decimal
import stripe
from django.db import models
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_tx
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as tz
from django.views.decorators.http import require_POST, require_http_methods
from django.core.mail import send_mail
from django.template.loader import render_to_string

from cart_user.models import Cart
from order_user.models import Order, OrderItem
from customers.models import Address
from coupon_admin.models import Coupon, CouponUsage
from wallet_user.models import Wallet, WalletTransaction
from checkout_page.models import StripePayment
from offer_admin.models import BaseOffer


stripe.api_key = settings.STRIPE_SECRET_KEY

FREE_SHIPPING_THRESHOLD = Decimal('999')
SHIPPING_CHARGE         = Decimal('79')
COD_FEE                 = Decimal('0')

COUNTRIES = [
    'India', 'United States', 'United Kingdom',
    'UAE', 'Singapore', 'Canada', 'Australia', 'Other',
]



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


def _item_price(item):
    return item.variant.price if (item.variant and item.variant.price) else item.product.price
 
 
def _send_order_confirmation_email(order, user):
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    try:
        subject = f'Order Confirmed #{str(order.uuid)[:8].upper()} — Veska'
        body = render_to_string('emails/order_confirmation.txt', {
            'order': order, 'user': user, 'items': order.items.all(),
        })
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
                  [user.email], fail_silently=True)
    except Exception as e:
        print(f'[EMAIL ERROR] {e}')


def _enrich_coupons(coupons_qs, subtotal, user):
   
    now = tz.now()
    used_ids = set(
        CouponUsage.objects.filter(user=user).values_list('coupon_id', flat=True)
    )
    result = []
    for coupon in coupons_qs:
        is_valid     = True
        valid_message = ''
        saved_amount  = Decimal('0')

        if coupon.id in used_ids:
            is_valid      = False
            valid_message = 'Already used by you'
        elif coupon.usage_limit and coupon.times_used >= coupon.usage_limit:
            is_valid      = False
            valid_message = 'Usage limit reached'
        elif coupon.valid_until and coupon.valid_until < now:
            is_valid      = False
            valid_message = 'Expired'
        elif coupon.min_order_value and subtotal < coupon.min_order_value:
            is_valid      = False
            valid_message = f'Min order ₹{coupon.min_order_value} required'
        else:
            if coupon.discount_type == 'percentage':
                disc = (subtotal * coupon.value / 100).quantize(Decimal('0.01'))
                if coupon.max_discount:
                    disc = min(disc, coupon.max_discount)
            else:
                disc = coupon.value
            saved_amount = disc

        result.append({
            'coupon':        coupon,
            'is_valid':      is_valid,
            'saved_amount':  saved_amount,
            'valid_message': valid_message,
        })
    return result



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
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if is_ajax:
        try:
            body = json.loads(request.body)
            code = body.get('coupon_code', '').strip().upper()
        except (json.JSONDecodeError, KeyError):
            return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)
    else:
        code = request.POST.get('coupon_code', '').strip().upper()

    if not code:
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'Please enter a coupon code.'})
        messages.error(request, 'Please enter a coupon code.')
        return redirect('checkout')

    if request.session.get('coupon_code'):
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'A coupon is already applied. Remove it first.'})
        messages.warning(request, 'A coupon is already applied. Remove it first.')
        return redirect('checkout')

    try:
        coupon = Coupon.objects.get(code__iexact=code, is_active=True)
    except Coupon.DoesNotExist:
        if is_ajax:
            return JsonResponse({'success': False, 'error': f'"{code}" is not a valid coupon code.'})
        messages.error(request, f'"{code}" is not a valid coupon code.')
        return redirect('checkout')

    now = tz.now()
    if coupon.valid_until and coupon.valid_until < now:
        msg = 'This coupon has expired.'
        if is_ajax:
            return JsonResponse({'success': False, 'error': msg})
        messages.error(request, msg)
        return redirect('checkout')

    if coupon.usage_limit and coupon.times_used >= coupon.usage_limit:
        msg = 'This coupon has reached its usage limit.'
        if is_ajax:
            return JsonResponse({'success': False, 'error': msg})
        messages.error(request, msg)
        return redirect('checkout')

    if CouponUsage.objects.filter(user=request.user, coupon=coupon).exists():
        msg = 'You have already used this coupon.'
        if is_ajax:
            return JsonResponse({'success': False, 'error': msg})
        messages.error(request, msg)
        return redirect('checkout')

    cart     = _get_cart(request)
    subtotal = sum(_item_price(i) * i.quantity for i in cart.items.all())

    if coupon.min_order_value and subtotal < coupon.min_order_value:
        msg = f'Minimum order of ₹{coupon.min_order_value} required for this coupon.'
        if is_ajax:
            return JsonResponse({'success': False, 'error': msg})
        messages.error(request, msg)
        return redirect('checkout')

    if coupon.discount_type == 'percentage':
        discount = (subtotal * coupon.value / 100).quantize(Decimal('0.01'))
        if coupon.max_discount:
            discount = min(discount, coupon.max_discount)
    else:
        discount = coupon.value

    request.session['coupon_code']     = coupon.code
    request.session['coupon_discount'] = str(discount)

    if is_ajax:
        return JsonResponse({
            'success':  True,
            'message':  f'Coupon "{coupon.code}" applied — you save ₹{discount:.2f}!',
            'code':     coupon.code,
            'discount': str(discount),
        })
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
    selected  = addresses.filter(is_default=True).first() or addresses.first()

    try:
        wallet_balance = Wallet.objects.get(user=request.user).balance
    except Wallet.DoesNotExist:
        wallet_balance = Decimal('0')

    enriched_items = []
    for item in cart_items:
        enriched_items.append({
            'product':    item.product,
            'variant':    item.variant,
            'quantity':   item.quantity,
            'unit_price': _item_price(item),
            'line_total': _item_price(item) * item.quantity,
        })

    now = tz.now()

    raw_coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=now,
    ).filter(
        models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=now)
    )
    available_coupons = _enrich_coupons(raw_coupons, subtotal, request.user)

    available_offers = BaseOffer.objects.filter(
        is_active=True,
        start_date__lte=now,
        end_date__gte=now,
    )

    return render(request, 'checkout.html', {
        'cart_items':       enriched_items,
        'subtotal':         totals['subtotal'],
        'coupon_code':      coupon_code,
        'coupon_discount':  totals['coupon_discount'],
        'shipping':         totals['shipping'],
        'grand_total':      totals['grand_total'],
        'addresses':        addresses,
        'selected_id':      str(selected.id) if selected else '',
        'free_threshold':   FREE_SHIPPING_THRESHOLD,
        'wallet_balance':   wallet_balance,
        'cod_fee':          COD_FEE,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
        'available_coupons': available_coupons,   
        'available_offers':  available_offers,
    })




@login_required(login_url='login')
@require_http_methods(['POST'])
def stripe_create_checkout_session(request):
    try:
        data          = json.loads(request.body)
        address_id    = data.get('address_id')
        wallet_amount = Decimal(str(data.get('wallet_amount', '0')))
        notes         = data.get('notes', '')

        if not address_id:
            return JsonResponse({'error': 'Please select a delivery address.'}, status=400)

        address    = get_object_or_404(Address, id=address_id, user=request.user)
        cart       = _get_cart(request)
        cart_items = cart.items.select_related('variant', 'product').all()

        if not cart_items.exists():
            return JsonResponse({'error': 'Cart is empty'}, status=400)

        subtotal = sum(_item_price(item) * item.quantity for item in cart_items)

        coupon_code     = request.session.get('coupon_code', '')
        coupon_discount = Decimal(request.session.get('coupon_discount', '0'))

        shipping_amount = SHIPPING_CHARGE if (subtotal - coupon_discount) < FREE_SHIPPING_THRESHOLD else Decimal('0')
        amount_to_pay   = max(subtotal - coupon_discount + shipping_amount - wallet_amount, Decimal('0'))

        if amount_to_pay == 0:
            return JsonResponse({'success': True, 'wallet_only': True, 'amount': 0})

        checkout_session = stripe.checkout.Session.create(
            customer_email=request.user.email,
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'inr',
                    'unit_amount': int(amount_to_pay * 100),
                    'product_data': {
                        'name':        'Veska Order',
                        'description': f'{cart_items.count()} item(s) – Total ₹{amount_to_pay}',
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.build_absolute_uri(reverse('payment_success')) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.build_absolute_uri(reverse('payment_cancel'))   + '?session_id={CHECKOUT_SESSION_ID}',
            metadata={
                'cart_id':         str(cart.id),
                'user_id':         str(request.user.pk),
                'address_id':      str(address_id),
                'wallet_amount':   str(wallet_amount),
                'notes':           notes,
                'coupon_code':     coupon_code,
                'coupon_discount': str(coupon_discount),
                'shipping_amount': str(shipping_amount),
                'subtotal':        str(subtotal),
            },
        )

        StripePayment.objects.create(
            user=request.user,
            session_id=checkout_session.id,
            amount=amount_to_pay,
            status='pending',
            metadata={
                'cart_id':       str(cart.id),
                'address_id':    str(address_id),
                'wallet_amount': str(wallet_amount),
                'notes':         notes,
                'coupon_code':   coupon_code,
            },
        )

        return JsonResponse({
            'success':      True,
            'checkout_url': checkout_session.url,
            'session_id':   checkout_session.id,
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)



@login_required(login_url='login')
def payment_success(request):
    session_id = request.GET.get('session_id')

    if not session_id:
        messages.error(request, 'Invalid payment session.')
        return redirect('home')

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.InvalidRequestError as e:
        print(f'[payment_success] Stripe InvalidRequestError: {e}')
        messages.error(request, 'Payment session not found. Please contact support.')
        return redirect('payment_cancel')
    except stripe.error.StripeError as e:
        print(f'[payment_success] StripeError: {e}')
        messages.error(request, 'Could not verify payment with Stripe. Please try again.')
        return redirect('payment_cancel')

    payment_status = session.payment_status
    session_status = session.status
    print(f'[payment_success] session_id={session_id} '
          f'payment_status={payment_status} session_status={session_status}')

    if payment_status not in ('paid', 'no_payment_required'):
        print(f'[payment_success] Rejecting — payment_status={payment_status}')
        messages.error(request,
            'Payment is not confirmed yet. '
            'If you completed payment, please wait a few minutes and try again.')
        return redirect('payment_cancel')

    try:
        payment = StripePayment.objects.get(session_id=session_id, user=request.user)
    except StripePayment.DoesNotExist:
        try:
            payment = StripePayment.objects.get(session_id=session_id)
            print(f'[payment_success] User mismatch: '
                  f'payment.user={payment.user_id}, request.user={request.user.pk}')
        except StripePayment.DoesNotExist:
            messages.error(request,
                f'Payment record not found. Please contact support. '
                f'Session ID: {session_id}')
            return redirect('payment_cancel')

    if payment.order:
        print(f'[payment_success] Order already exists: {payment.order.uuid}')
        _send_order_confirmation_email(payment.order, request.user)
        return redirect('order_success', uuid=payment.order.uuid)

  
    try:
        raw_meta = payment.metadata        
        
        address_id      = int(raw_meta.get('address_id') or 0)
        wallet_amount   = Decimal(str(raw_meta.get('wallet_amount')   or '0'))
        notes           = raw_meta.get('notes')           or ''
        coupon_code     = raw_meta.get('coupon_code')     or ''
        coupon_discount = Decimal(str(raw_meta.get('coupon_discount') or '0'))
        shipping_amount = Decimal(str(raw_meta.get('shipping_amount') or '0'))
        subtotal        = Decimal(str(raw_meta.get('subtotal')        or '0'))
        cart_id         = int(raw_meta.get('cart_id') or 0)
    except (ValueError, TypeError) as e:
        print(f'[payment_success] Metadata parse error: {e}')
        messages.error(request, 'Order data is corrupted. Please contact support.')
        return redirect('payment_cancel')

    print(f'[payment_success] address_id={address_id} cart_id={cart_id} '
          f'subtotal={subtotal} coupon={coupon_code} shipping={shipping_amount}')

    if not address_id:
        messages.error(request, 'Delivery address missing from payment data.')
        return redirect('payment_cancel')

    try:
        address = Address.objects.get(id=address_id, user=request.user)
    except Address.DoesNotExist:
        try:
            address = Address.objects.get(id=address_id)
        except Address.DoesNotExist:
            messages.error(request, 'Delivery address not found. Please contact support.')
            return redirect('payment_cancel')

    cart       = None
    cart_items = []
    if cart_id:
        try:
            cart       = Cart.objects.get(id=cart_id, user=request.user)
            cart_items = list(cart.items.select_related('variant', 'product').all())
        except Cart.DoesNotExist:
            print(f'[payment_success] Cart {cart_id} not found for user {request.user.pk}')

    if not cart_items:
        payment.status            = 'completed'
        payment.payment_intent_id = session.payment_intent
        payment.save(update_fields=['status', 'payment_intent_id'])
        messages.success(request,
            'Your payment was successful! Our team will confirm your order shortly.')
        return redirect('home')

    total_paid = Decimal(str(session.amount_total or 0)) / 100

    try:
        with db_tx.atomic():
            order = Order.objects.create(
                user=request.user,
                full_name=address.full_name,
                phone=address.phone,
                address_line1=address.address_line1,
                address_line2=address.address_line2 or '',
                city=address.city,
                state=address.state,
                pincode=address.pincode,
                country=address.country,
                subtotal=subtotal,
                coupon_code=coupon_code,
                discount_amount=coupon_discount,
                shipping_charge=shipping_amount,
                wallet_amount_used=wallet_amount,
                total=total_paid,
                payment_method='stripe',
                payment_status='paid',
                status='confirmed',
                notes=notes,
            )

            for item in cart_items:
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

            if coupon_code:
                try:
                    coupon_obj = Coupon.objects.get(code=coupon_code, is_active=True)
                    coupon_obj.times_used += 1
                    coupon_obj.save(update_fields=['times_used'])
                    CouponUsage.objects.get_or_create(
                        user=request.user, coupon=coupon_obj,
                        defaults={'order': order},
                    )
                except Coupon.DoesNotExist:
                    pass

            if wallet_amount > 0:
                try:
                    wallet_obj = Wallet.objects.get(user=request.user)
                    wallet_obj.balance = max(Decimal('0'), wallet_obj.balance - wallet_amount)
                    wallet_obj.save(update_fields=['balance'])
                    WalletTransaction.objects.create(
                        user=request.user,
                        amount=-wallet_amount,
                        transaction_type='DEBIT',
                        order=order,
                        description=f'Payment for order {order.uuid} (Stripe + Wallet)',
                    )
                except Wallet.DoesNotExist:
                    print(f'[payment_success] Wallet not found for user {request.user.pk}')

            if cart:
                cart.items.all().delete()

            for key in ('coupon_code', 'coupon_discount'):
                request.session.pop(key, None)

            payment.order             = order
            payment.status            = 'completed'
            payment.payment_intent_id = session.payment_intent
            payment.save()

    except Exception as e:
        import traceback
        traceback.print_exc()
        messages.error(request,
            f'Your payment was received but we could not create your order. '
            f'Please contact support with session ID: {session_id}')
        return redirect('home')

    _send_order_confirmation_email(order, request.user)

    return redirect('order_success', uuid=order.uuid)
 


@login_required(login_url='login')
def payment_cancel(request):
    session_id = request.GET.get('session_id')
    if session_id:
        try:
            payment = StripePayment.objects.filter(session_id=session_id, user=request.user).first()
            if payment and payment.status == 'pending':
                payment.status = 'failed'
                payment.save()
        except Exception as e:
            print(f'[payment_cancel] {e}')
    return render(request, 'payment_failure.html', {
        'retry_url': reverse('cart_detail'),
        'session_id': session_id,
    })


@csrf_exempt
@require_http_methods(['POST'])
def stripe_webhook(request):
    payload       = request.body
    sig_header    = request.META.get('HTTP_STRIPE_SIGNATURE')
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET

    if not webhook_secret:
        if settings.DEBUG:
            try:
                event = json.loads(payload)
            except Exception:
                return HttpResponse(status=400)
        else:
            return HttpResponse(status=400)
    else:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError):
            return HttpResponse(status=400)

    if event['type'] == 'checkout.session.completed':
        _wh_checkout_completed(event['data']['object'])
    elif event['type'] == 'checkout.session.async_payment_failed':
        _wh_payment_failed(event['data']['object'])

    return HttpResponse(status=200)


def _wh_checkout_completed(session):
    try:
        payment = StripePayment.objects.get(session_id=session['id'])
        payment.status             = 'completed'
        payment.payment_intent_id  = session.get('payment_intent')
        payment.save()
    except StripePayment.DoesNotExist:
        pass


def _wh_payment_failed(session):
    try:
        payment        = StripePayment.objects.get(session_id=session['id'])
        payment.status = 'failed'
        payment.save()
    except StripePayment.DoesNotExist:
        pass



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

        address    = get_object_or_404(Address, pk=address_id, user=request.user)
        cart       = _get_cart(request)
        items      = cart.items.select_related('variant', 'product').all()

        if not items.exists():
            return JsonResponse({'error': 'Cart is empty.'}, status=400)

        subtotal = sum(_item_price(i) * i.quantity for i in items)

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
                    f'Please use Stripe for the remaining amount.'
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
                payment_status='pending' if payment_method == 'cod' else 'paid',
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
                    defaults={'order': order},
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

            _send_order_confirmation_email(order, request.user)

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
    order       = get_object_or_404(Order, uuid=uuid, user=request.user)
    estimated   = order.created_at + datetime.timedelta(days=5)
    order_items = order.items.all()
    return render(request, 'order_success.html', {
        'order':              order,
        'order_items':        order_items,
        'estimated_delivery': estimated.strftime('%d %b %Y'),
    })