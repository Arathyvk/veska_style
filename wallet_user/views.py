from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db import transaction

from wallet_user.models import Wallet, WalletTransaction


def get_or_create_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def is_admin(user):
    return user.is_staff or user.is_superuser



@login_required
def wallet_dashboard(request):
    wallet       = get_or_create_wallet(request.user)
    transactions = wallet.transactions.select_related('order').all()

    txn_filter = request.GET.get('filter', 'all')
    if txn_filter == 'credit':
        transactions = transactions.filter(transaction_type=WalletTransaction.CREDIT)
    elif txn_filter == 'debit':
        transactions = transactions.filter(transaction_type=WalletTransaction.DEBIT)

    paginator = Paginator(transactions, 10)
    page      = request.GET.get('page', 1)
    txn_page  = paginator.get_page(page)

    total_credited = sum(
        t.amount for t in wallet.transactions.filter(transaction_type=WalletTransaction.CREDIT)
    )
    total_debited  = sum(
        t.amount for t in wallet.transactions.filter(transaction_type=WalletTransaction.DEBIT)
    )

    context = {
        'wallet':         wallet,
        'transactions':   txn_page,
        'txn_filter':     txn_filter,
        'total_credited': total_credited,
        'total_debited':  total_debited,
    }
    return render(request, 'wallet_dashboard.html', context)




@transaction.atomic
def refund_on_cancellation(order):
    
    if order.payment_method == 'cod':
        return  

    wallet = get_or_create_wallet(order.user)
    wallet.credit(
        amount      = order.grand_total,
        reason      = WalletTransaction.REASON_CANCELLATION,
        order       = order,
        description = f"Refund for cancelled order #{order.uuid}",
    )



@transaction.atomic
def refund_on_return_approval(order):
    
    if order.payment_method == 'cod':
        return  
    wallet = get_or_create_wallet(order.user)
    wallet.credit(
        amount      = order.grand_total,
        reason      = WalletTransaction.REASON_RETURN,
        order       = order,
        description = f"Refund for returned order #{order.uuid}",
    )



@transaction.atomic
def debit_wallet_for_order(order, amount):
    if amount <= 0:
        return
 
    wallet = get_or_create_wallet(order.user)
    wallet.debit(
        amount      = amount,
        reason      = WalletTransaction.REASON_PAYMENT,
        order       = order,
        description = f"Payment for order #{order.uuid}",
    )




@login_required
def wallet_balance_api(request):
    wallet = get_or_create_wallet(request.user)
    return JsonResponse({'balance': str(wallet.balance)})




