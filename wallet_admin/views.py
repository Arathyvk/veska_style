import json

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db import transaction
from decimal import Decimal


from wallet_user.models import Wallet, WalletTransaction
from wallet_user.utils import refund_on_return_approval
from order_user.models import Order         


def get_or_create_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet
 
 
def is_admin(user):
    return user.is_staff or user.is_superuser


@login_required
@user_passes_test(is_admin)
def admin_wallet_list(request):
    wallets = Wallet.objects.select_related('user').order_by('-balance')
    search  = request.GET.get('q', '').strip()
    if search:
        wallets = wallets.filter(user__email__icontains=search)
 
    paginator = Paginator(wallets, 20)
    page      = paginator.get_page(request.GET.get('page', 1))
 
    return render(request, 'wallet_list.html', {
        'wallets': page,
        'search':  search,
    })
 
  
@login_required
@user_passes_test(is_admin)
def admin_wallet_detail(request, wallet_id):
    wallet       = get_object_or_404(Wallet, pk=wallet_id)
    transactions = wallet.transactions.select_related('order').all()
    paginator    = Paginator(transactions, 15)
    txn_page     = paginator.get_page(request.GET.get('page', 1))
 
    return render(request, 'wallet_detail.html', {
        'wallet':       wallet,
        'transactions': txn_page,
    })
 

@login_required
@user_passes_test(is_admin)
@require_POST
def admin_wallet_adjust(request, wallet_id):
    wallet = get_object_or_404(Wallet, pk=wallet_id)
 
    try:
        body   = json.loads(request.body)
        action = body.get('action')          
        amount = Decimal(str(body.get('amount', 0)))
        note   = body.get('note', '')[:255]
 
        if amount <= 0:
            return JsonResponse({'success': False, 'error': 'Amount must be greater than zero.'})
 
        if action == 'credit':
            wallet.credit(
                amount      = amount,
                reason      = WalletTransaction.REASON_MANUAL,
                description = note or 'Manual credit by admin',
            )
            return JsonResponse({'success': True, 'balance': str(wallet.balance), 'action': 'credit'})
 
        elif action == 'debit':
            wallet.debit(
                amount      = amount,
                reason      = WalletTransaction.REASON_MANUAL,
                description = note or 'Manual debit by admin',
            )
            return JsonResponse({'success': True, 'balance': str(wallet.balance), 'action': 'debit'})
 
        else:
            return JsonResponse({'success': False, 'error': 'Invalid action.'})
 
    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'An error occurred.'})
 

@login_required
@user_passes_test(is_admin)
@require_POST
def admin_approve_return(request, order_id):
    order = get_object_or_404(Order, pk=order_id)

    if order.status != 'return_requested':
        messages.error(request, 'This order is not in a returnable state.')
        return redirect('admin_order_detail', uuid=order.uuid)

    with transaction.atomic():
        order.status = 'returned'
        order.save(update_fields=['status'])
        refund_amount = refund_on_return_approval(order)

    if refund_amount:
        messages.success(
            request,
            f"Return approved. ₹{refund_amount} refunded to {order.user.email}'s wallet."
        )
    else:
        messages.warning(
            request,
            f"Return marked as approved but no refund was issued "
            f"(payment method: {order.payment_method}, status: {order.payment_status})."
        )
    return redirect('admin_order_detail', uuid=order.uuid)