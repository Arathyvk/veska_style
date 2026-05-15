import hmac
import hashlib
import razorpay

from decimal import Decimal
from django.conf import settings
from django.contrib import messages
from django.db import transaction as db_tx
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import render,get_object_or_404,redirect
from django.contrib.auth.decorators import login_required



from order_user.models import Order
from payment_user.models import RazorpayTransaction

client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET )
)

CANCEL_REASONS =[
    ('changed_mind',   'Changed my mind'),
    ('wrong_item',     'Orderes wrong item/size'),
    ('found_cheaper',  'Found better price elsewhere'),
    ('delivery_delay', 'Delivery is taking too long'),
    ('payment_issue',  'Payment issue'),
    ('other',          'other'),

]

RETURN_REASONS = [
    ('wrong_size',        'Wrong size received'),
    ('wrong_item',        'Wrong item received'),
    ('defective',         'Defective / damaged product'),
    ('not_as_described',  'Not as described'),
    ('changed_mind',      'Changed my mind'),
    ('quality_issue',     'Quality not as expected'),
    ('other',             'Other'),
]


@login_required
def razorpay_create_order(request, order_number):
    order = get_object_or_404(
        Order,
        order_number=order_number,
        user=request.user

    )

    if order.payment_status == 'paid':
        return redirect('payment_success', order_number=order_number)
    

    amount_paise = int(order.total * 100)

    rz_order =  client.order.create({
        'amount': amount_paise,
        'currency': 'INR',
        'receipt': order_number,
        'notes': {'order_number' : order_number},
    })


    txn = RazorpayTransaction.objects.create(
        order=order,
        razorpay_order_id=rz_order['id'],
        amount=order.total,
        status='created',
    )

    return render(request, 'payment_success.html', {
        'order': order,
        'rz_order_id': rz_order['id'],
        'rz_key': settings.RAZORPAY_KEY_ID,
        'amount_paise': amount_paise,
        'amount_display': order.total,
        

    })


@csrf_exempt
@require_POST
def razorpay_verify(request):
    order_number   = request.POST.get('order_number')
    rz_order_id    = request.POST.get('razorpay_order_id')
    rz_payment_id  = request.POST.get('razorpay_payment_id')
    rz_signature   = request.POST.get('razorpay_signature')


    order = get_object_or_404(Order,order_number=order_number)
    txn   = RazorpayTransaction.objects.filter(
        order=order,
        razorpay_order_id=rz_order_id
    ).first()


    body  = f"{rz_order_id}|{rz_payment_id}"
    expected =hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        body.encode(),
        hashlib.sha256,

    ).hexdigest()


    if not hmac.compare_digest(expected, rz_signature):
        if txn:
            txn.status = 'failed'
            txn.failure_reason = 'Signature mismatch'
            txn.save()

        return redirect('payment_failure', order_number=order_number)

    with db_tx.atomic():
        if txn:
            txn.razorpay_payment_id = rz_payment_id
            txn.razorpay_signature  = rz_signature
            txn.status              = 'paid'
            txn.save()

        order.status          = 'confirmed'
        order.payment_status  = 'paid'
        order.payment_method  = 'razorpay'
        order.save()


        # if order.wallet_amount_used > 0:
        #     try:
        #         # wallet = Wallet.get_or_create_for_user(order.user)
        #         wallet.debit(
        #             amount = order.wallet_amount_used,
        #             description = f"Wallet payment for order #{order_number}",
        #             reason = 'ORDER_PAYMENT',
        #             order = order,
        #         )
        #     except Exception:
        #         pass

    return redirect('payment_success', order_number=order_number)    



@login_required
def payment_success(request, order_number):

    order = get_object_or_404(
        Order,
        order_number = order_number,
        user = request.user
    )

    return render(request, 'payment_success.html',{'order_number':order_number})


@login_required
def payment_failure(request, order_number):
    order = get_object_or_404(
        Order,
        order_number = order_number,
        user = request.user
    ) 

    txn = RazorpayTransaction.objects.filter(order=order).order_by('-created_at').first()

    return render(request, 'payment_failure.html', {
        'order': order,
        'txn'  : txn,

    })         


