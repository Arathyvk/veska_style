import hmac
import hashlib

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
from django.views.decorators.http import require_POST




from order_user.models import Order



@login_required(login_url='login')
def payment_failure(request):
    reason = request.GET.get('reason', 'Payment was not completed.')
    return render(request, 'payment_failed.html', {'reason': reason})
 