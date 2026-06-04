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
    print("CHECKOUT USER:", request.user)
    print("CHECKOUT AUTH:", request.user.is_authenticated)

    cart = _get_cart(request)
    cart_items = cart.items.select_related('variant', 'variant__product', 'product').all()

    if not cart_items.exists():
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart_detail')

    subtotal = sum(_item_price(i) * i.quantity for i in cart_items)
    coupon_code = request.session.get('coupon_code', '')
    coupon_discount = Decimal(request.session.get('coupon_discount', '0'))

    if coupon_code:
        try:
            Coupon.objects.get(code=coupon_code, is_active=True)
        except Coupon.DoesNotExist:
            coupon_code = ''
            coupon_discount = Decimal('0')
            request.session.pop('coupon_code', None)
            request.session.pop('coupon_discount', None)

    totals = _calc_totals(subtotal, coupon_discount)
    addresses = request.user.addresses.all()
    selected = addresses.filter(is_default=True).first() or addresses.first()

    try:
        wallet_balance = Wallet.objects.get(user=request.user).balance
    except Wallet.DoesNotExist:
        wallet_balance = Decimal('0')

    enriched = []
    for item in cart_items:
        enriched.append({
            'product': item.product,
            'variant': item.variant,
            'quantity': item.quantity,
            'unit_price': _item_price(item),
            'line_total': _item_price(item) * item.quantity,
        })

    now = tz.now()

    used_ids = CouponUsage.objects.filter(user=request.user).values_list('coupon_id', flat=True)
    available_coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=now,
    ).filter(
        models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=now)
    ).exclude(id__in=used_ids)

    available_offers = BaseOffer.objects.filter(
        is_active=True,
        start_date__lte=now,
        end_date__gte=now,
    )

    return render(request, 'checkout.html', {
        'cart_items': enriched,
        'subtotal': totals['subtotal'],
        'coupon_code': coupon_code,
        'coupon_discount': totals['coupon_discount'],
        'shipping': totals['shipping'],
        'grand_total': totals['grand_total'],
        'addresses': addresses,
        'selected_id': str(selected.id) if selected else '',
        'free_threshold': FREE_SHIPPING_THRESHOLD,
        'wallet_balance': wallet_balance,
        'cod_fee': COD_FEE,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
        'available_coupons': available_coupons,
        'available_offers': available_offers,
    })


@login_required(login_url='login')
@require_http_methods(['POST'])
def stripe_create_checkout_session(request):
    try:
        data = json.loads(request.body)
        address_id = data.get('address_id')
        wallet_amount = Decimal(str(data.get('wallet_amount', '0')))
        notes = data.get('notes', '')
        
        if not address_id:
            return JsonResponse({'error': 'Please select a delivery address.'}, status=400)
        
        address = get_object_or_404(Address, id=address_id, user=request.user)
        
        cart = _get_cart(request)
        cart_items = cart.items.select_related('variant', 'product').all()
        
        if not cart_items.exists():
            return JsonResponse({'error': 'Cart is empty'}, status=400)
        
        subtotal = sum(_item_price(item) * item.quantity for item in cart_items)
        
        coupon_code = request.session.get('coupon_code', '')
        coupon_discount = Decimal(request.session.get('coupon_discount', '0'))
        
        shipping_amount = SHIPPING_CHARGE if subtotal - coupon_discount < FREE_SHIPPING_THRESHOLD else Decimal('0')
        
        amount_to_pay = subtotal - coupon_discount + shipping_amount - wallet_amount
        
        if amount_to_pay <= 0:
            return JsonResponse({
                'success': True,
                'wallet_only': True,
                'amount': float(amount_to_pay)
            })
        
        checkout_session = stripe.checkout.Session.create(
            customer_email=request.user.email,
            payment_method_types=['card', 'upi'],
            line_items=[{
                'price_data': {
                    'currency': 'inr',
                    'unit_amount': int(amount_to_pay * 100),
                    'product_data': {
                        'name': f'Veska Order',
                        'description': f'{cart_items.count()} item(s) - Total: ₹{amount_to_pay}',
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.build_absolute_uri(reverse('payment_success')) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.build_absolute_uri(reverse('payment_cancel')) + '?session_id={CHECKOUT_SESSION_ID}',
            metadata={
                'cart_id': cart.id,
                'user_id': request.user.pk,
                'address_id': address_id,
                'wallet_amount': str(wallet_amount),
                'notes': notes,
                'coupon_code': coupon_code,
                'coupon_discount': str(coupon_discount),
                'shipping_amount': str(shipping_amount),
                'subtotal': str(subtotal),
            },
        )
        
        StripePayment.objects.create(
            user=request.user,
            session_id=checkout_session.id,
            amount=amount_to_pay,
            status='pending',
            metadata={
                'cart_id': cart.id,
                'address_id': address_id,
                'wallet_amount': str(wallet_amount),
                'notes': notes,
                'coupon_code': coupon_code,
            }
        )
        
        return JsonResponse({
            'success': True,
            'checkout_url': checkout_session.url,
            'session_id': checkout_session.id
        })
        
    except Exception as e:
        print(f"Stripe error: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)



@login_required(login_url='login')
def payment_success(request):
    session_id = request.GET.get('session_id')

    if not session_id:
        messages.error(request, 'Invalid payment session.')
        return redirect('home')

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        print(f"[DEBUG] payment_success - session_id={session_id}, payment_status={session.payment_status}")

        # Accept both 'paid' and 'unpaid' statuses; unpaid can occur with async methods (UPI)
        # The key indicator is that the session was successfully created and the customer reached this page
        if session.payment_status not in ('paid', 'unpaid'):
            messages.error(request, 'Payment session invalid.')
            return redirect('payment_cancel')

        
        payment = get_object_or_404(StripePayment, session_id=session_id, user=request.user)

        if payment.order:
            return redirect('order_success', uuid=payment.order.uuid)

        metadata = dict(session.metadata)

        
        address_id      = int(metadata.get('address_id', 0))
        wallet_amount   = Decimal(str(metadata.get('wallet_amount', '0')))
        notes           = metadata.get('notes', '')
        coupon_code     = metadata.get('coupon_code', '')
        coupon_discount = Decimal(str(metadata.get('coupon_discount', '0')))
        shipping_amount = Decimal(str(metadata.get('shipping_amount', '0')))
        subtotal        = Decimal(str(metadata.get('subtotal', '0')))

        address = get_object_or_404(Address, id=address_id, user=request.user)

        cart_id = int(metadata.get('cart_id', 0))
        try:
            cart = Cart.objects.get(id=cart_id, user=request.user)
            cart_items = cart.items.select_related('variant', 'product').all()
        except Cart.DoesNotExist:
            cart = None
            cart_items = []

        if not cart_items:
            payment.status = 'completed'
            payment.payment_intent_id = session.payment_intent
            payment.save(update_fields=['status', 'payment_intent_id'])
            messages.success(
                request,
                'Your payment was successful! Our team will confirm your order shortly.'
            )
            return redirect('home')

        total_paid = Decimal(str(session.amount_total)) / 100

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
                img = item.product.images.first()
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
                    coupon = Coupon.objects.get(code=coupon_code, is_active=True)
                    coupon.times_used += 1
                    coupon.save(update_fields=['times_used'])
                    CouponUsage.objects.get_or_create(
                        user=request.user, coupon=coupon,
                        defaults={'order': order}
                    )
                except Coupon.DoesNotExist:
                    pass

            if wallet_amount > 0:
                wallet = Wallet.objects.get(user=request.user)
                wallet.balance -= wallet_amount
                wallet.save(update_fields=['balance'])
                WalletTransaction.objects.create(
                    user=request.user,
                    amount=-wallet_amount,
                    transaction_type='DEBIT',
                    order=order,
                    description=f'Payment for order {order.uuid} (Stripe + Wallet)',
                )

            cart.items.all().delete()

            for key in ['coupon_code', 'coupon_discount']:
                request.session.pop(key, None)

            payment.order = order
            payment.status = 'completed'
            payment.payment_intent_id = session.payment_intent
            payment.save()

        return redirect('order_success', uuid=order.uuid)

    except StripePayment.DoesNotExist:
        messages.error(request, 'Payment record not found. Please contact support.')
        return redirect('payment_cancel')
    except Exception as e:
        import traceback
        traceback.print_exc()
        messages.error(request, f'Unable to verify payment: {str(e)}')
        return redirect('payment_cancel')


@login_required(login_url='login')
def payment_cancel(request):
    session_id = request.GET.get('session_id')
    print(f"[DEBUG] payment_cancel - session_id={session_id}")
    
    if session_id:
        try:
            payment = StripePayment.objects.filter(session_id=session_id, user=request.user).first()
            print(f"[DEBUG] payment_cancel - payment found: {payment is not None}")
            if payment and payment.status == 'pending':
                payment.status = 'failed'
                payment.save()
                print(f"[DEBUG] payment_cancel - marked as failed")
        except Exception as e:
            print(f"[DEBUG] Error updating payment status: {e}")
    
    return render(request, 'payment_failure.html', {
        'retry_url': reverse('cart_detail'),
        'session_id': session_id
    })


@csrf_exempt
@require_http_methods(['POST'])
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET
    
    if not webhook_secret:
        if settings.DEBUG:
            try:
                event = json.loads(payload)
            except:
                return HttpResponse(status=400)
        else:
            return HttpResponse(status=400)
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except ValueError:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError:
            return HttpResponse(status=400)
    
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_completed(session)
    elif event['type'] == 'checkout.session.async_payment_failed':
        session = event['data']['object']
        handle_payment_failed(session)
    elif event['type'] == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        handle_payment_intent_failed(payment_intent)
    
    return HttpResponse(status=200)


def handle_checkout_completed(session):
    try:
        payment = StripePayment.objects.get(session_id=session.id)
        payment.status = 'completed'
        payment.payment_intent_id = session.payment_intent
        payment.save()
        print(f"Webhook: Payment completed for session {session.id}")
    except StripePayment.DoesNotExist:
        print(f"Webhook: Payment record not found for session: {session.id}")
    except Exception as e:
        print(f"Webhook error: {str(e)}")

def handle_payment_failed(session):
    try:
        payment = StripePayment.objects.get(session_id=session.id)
        payment.status = 'failed'
        payment.save()
        print(f"Webhook: Payment failed for session {session.id}")
    except StripePayment.DoesNotExist:
        print(f"Webhook: Payment record not found for session: {session.id}")

def handle_payment_intent_failed(payment_intent):
    print(f"Webhook: Payment intent {payment_intent.id} failed")


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
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)



@login_required(login_url='login')
def order_success(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)
    estimated = order.created_at + datetime.timedelta(days=5)
    order_items = order.items.all()
    
    return render(request, 'order_success.html', {
        'order': order,
        'order_items': order_items,
        'estimated_delivery': estimated.strftime('%d %b %Y'),
    })