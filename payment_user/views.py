import hmac
import hashlib
import razorpay
import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.contrib import messages

from order_user.models import Order
from cart_user.models import Cart
from decimal import Decimal


_rz_client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)



@login_required
def create_razorpay_order(request, uuid):
    
    order = get_object_or_404(Order, uuid=uuid, user=request.user)

    if order.payment_status == 'paid':
        return redirect('payment_success', uuid=uuid)

    amount_paise = int(order.total * 100)   
    rz_order = _rz_client.order.create({
        'amount':   amount_paise,
        'currency': 'INR',
        'receipt':  str(order.uuid),
        'notes':    {'uuid': order.uuid},
    })

    order.razorpay_order_id = rz_order['id']
    order.save(update_fields=['razorpay_order_id'])

    return render(request, 'razorpay_payment.html', {
        'order':          order,
        'rz_order_id':    rz_order['id'],
        'rz_key':         settings.RAZORPAY_KEY_ID,
        'amount_paise':   amount_paise,
        'amount_display': order.total,
    })


@login_required
def razorpay_payment_success(request):
    # Handle GET requests (failures/cancellations)
    if request.method == 'GET':
        error_reason = request.GET.get('reason', '')
        error_desc = request.GET.get('error_description', 'Payment was cancelled')
        
        # Try to find order from session or GET parameters
        razorpay_order_id = request.GET.get('razorpay_order_id', '')
        order = None
        
        if razorpay_order_id:
            order = Order.objects.filter(
                razorpay_order_id=razorpay_order_id,
                user=request.user
            ).first()
        
        if not order:
            # Try to get from session
            razorpay_order_id = request.session.get('razorpay_order_id', '')
            if razorpay_order_id:
                order = Order.objects.filter(
                    razorpay_order_id=razorpay_order_id,
                    user=request.user
                ).first()
        
        if order:
            # Redirect to failure page with order context
            failure_url = reverse('payment_failure_with_order', kwargs={'uuid': order.uuid})
            return redirect(f"{failure_url}?error_description={error_desc}&reason={error_reason}")
        else:
            # Redirect to generic failure page
            return redirect(f"{reverse('payment_failure')}?reason={error_reason}")
    
    # Handle POST requests (successful payments)
    razorpay_order_id   = request.POST.get('razorpay_order_id', '')
    razorpay_payment_id = request.POST.get('razorpay_payment_id', '')
    razorpay_signature  = request.POST.get('razorpay_signature', '')

    order = Order.objects.filter(
        razorpay_order_id=razorpay_order_id,
        user=request.user,
    ).first()

    if not order:
        return redirect('home')

    body     = f"{razorpay_order_id}|{razorpay_payment_id}"
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        body.encode(),
        hashlib.sha256,
    ).hexdigest()

    if hmac.compare_digest(expected, razorpay_signature):
        order.payment_status      = 'paid'
        order.razorpay_payment_id = razorpay_payment_id
        order.razorpay_signature  = razorpay_signature
        order.status              = 'confirmed'
        order.save(update_fields=[
            'payment_status', 'razorpay_payment_id',
            'razorpay_signature', 'status',
        ])

        try:
            cart = Cart.objects.get(user=request.user)   
            cart.items.all().delete()
        except Cart.DoesNotExist:                         
            pass

        return redirect('payment_success', uuid=order.uuid)

    else:
        order.payment_status = 'failed'
        order.save(update_fields=['payment_status'])

        failure_url = reverse('payment_failure_with_order', kwargs={'uuid': order.uuid})
        return redirect(
            f"{failure_url}"
            f"?error_code=SIGNATURE_MISMATCH"
            f"&error_description=Payment+verification+failed"
            f"&razorpay_order_id={razorpay_order_id}"
        )



@login_required
def payment_success(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)

    # For COD orders
    if order.payment_method == 'cod' and order.payment_status == 'pending':
        estimated = order.created_at + timedelta(days=5)
        return render(request, 'payment_success.html', {
            'order': order,
            'estimated_delivery': estimated.strftime('%d %b %Y'),
        })
    
    # For paid orders
    if order.payment_status == 'paid':
        estimated = order.created_at + timedelta(days=5)
        return render(request, 'payment_success.html', {
            'order': order,
            'estimated_delivery': estimated.strftime('%d %b %Y'),
        })
    
    # If order is not paid and not COD, redirect to appropriate failure page
    if order.payment_status == 'failed':
        return redirect('payment_failure_with_order', uuid=uuid)
    
    # For any other invalid state
    messages.error(request, 'Payment not completed. Please try again.')
    return redirect('cart_detail')



@login_required
def payment_failure_with_order(request, uuid):
   
    order = get_object_or_404(Order, uuid=uuid, user=request.user)

    amount = order.total

    razorpay_order_id = (
        getattr(order, 'razorpay_order_id', '')
        or request.GET.get('razorpay_order_id', '')
    )

    return render(request, 'payment_failure.html', {
        'order':             order,
        'grand_total':       amount,           
        'error_reason':      request.GET.get('error_description', 'Payment was declined by the bank'),
        'error_code':        request.GET.get('error_code', 'PAYMENT_FAILED'),
        'razorpay_order_id': razorpay_order_id,
        'failed_at':         timezone.now().strftime('%d %b %Y, %I:%M %p'),
    })



@login_required
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
            razorpay_order_id = razorpay_order_id or order.razorpay_order_id
        else:
            try:
    
                cart     = Cart.objects.get(user=request.user)
                items    = cart.items.select_related('variant', 'product').all()
    
                def _item_price(item):
                    return item.variant.price if (item.variant and item.variant.price) \
                        else item.product.price
    
                subtotal = sum(_item_price(i) * i.quantity for i in items)
    
                coupon_discount = Decimal(request.session.get('coupon_discount', '0'))
                FREE_SHIP       = Decimal('999')
                SHIP_CHARGE     = Decimal('79')
                shipping        = SHIP_CHARGE if subtotal < FREE_SHIP else Decimal('0')
                wallet_used     = Decimal(pending.get('wallet_amount', '0'))
    
                amount = max(subtotal - coupon_discount + shipping - wallet_used, Decimal('0'))
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





@login_required
@require_http_methods(["POST"])
def razorpay_verify_payment(request):
    try:
        data = json.loads(request.body)
        
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_signature = data.get('razorpay_signature')
        
        order = Order.objects.filter(
            razorpay_order_id=razorpay_order_id,
            user=request.user
        ).first()
        
        if not order:
            return JsonResponse({'success': False, 'error': 'Order not found'})
        
        body = f"{razorpay_order_id}|{razorpay_payment_id}"
        expected = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(),
            body.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if hmac.compare_digest(expected, razorpay_signature):
            order.payment_status = 'paid'
            order.razorpay_payment_id = razorpay_payment_id
            order.razorpay_signature = razorpay_signature
            order.status = 'confirmed'
            order.save()
            
            try:
                cart = Cart.objects.get(user=request.user)
                cart.items.all().delete()
            except:
                pass
            
            return JsonResponse({
                'success': True,
                'redirect_url': reverse('payment_success', kwargs={'uuid': order.uuid})
            })
        else:
            order.payment_status = 'failed'
            order.save(update_fields=['payment_status'])
            return JsonResponse({
                'success': False, 
                'error': 'Invalid signature',
                'redirect_url': reverse('payment_failure_with_order', kwargs={'uuid': order.uuid})
            })
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})