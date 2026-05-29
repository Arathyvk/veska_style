import razorpay
from django.conf import settings
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404, render, redirect


from order_user.models import Order
    

def payment_success(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)
    return render(request, "payment_success.html", {"order": order})


def payment_failure(request, uuid=None):
    if uuid:
        order = get_object_or_404(Order, uuid=uuid, user=request.user)
    else:
        razorpay_order_id = request.GET.get('razorpay_order_id')
        order = Order.objects.filter(
            razorpay_order_id=razorpay_order_id,
            user=request.user
        ).first()
    
    return render(request, "payment_failure.html", {"order": order})
