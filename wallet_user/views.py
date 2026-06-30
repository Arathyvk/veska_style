from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator

from wallet_user.models import WalletTransaction
from wallet_user.utils import (       
    get_or_create_wallet,
    refund_on_cancellation,
    refund_on_return_approval,
    debit_wallet_for_order,
)


@login_required
def wallet_dashboard(request):
    print(f"DEBUG: logged in as {request.user.email}")  
    wallet = get_or_create_wallet(request.user)
    print(f"DEBUG: wallet balance = {wallet.balance}")
    
    all_txns = wallet.transactions.all()
    print(f"DEBUG: Total transactions = {all_txns.count()}")
    for txn in all_txns[:5]:
        print(f"  - {txn.transaction_type}: ₹{txn.amount} ({txn.reason}) - {txn.description}")
    
    transactions = wallet.transactions.select_related('order').all()

    txn_filter = request.GET.get('filter', 'all')
    if txn_filter == 'credit':
        transactions = transactions.filter(transaction_type=WalletTransaction.CREDIT)
    elif txn_filter == 'debit':
        transactions = transactions.filter(transaction_type=WalletTransaction.DEBIT)

    paginator = Paginator(transactions, 10)
    txn_page = paginator.get_page(request.GET.get('page', 1))

    credit_txns = wallet.transactions.filter(transaction_type=WalletTransaction.CREDIT)
    debit_txns = wallet.transactions.filter(transaction_type=WalletTransaction.DEBIT)

    total_credited = sum(t.amount for t in credit_txns)
    total_debited = sum(t.amount for t in debit_txns)
    total_txns = wallet.transactions.count()

    return render(request, 'wallet_dashboard.html', {
        'wallet': wallet,
        'transactions': txn_page,
        'txn_filter': txn_filter,
        'total_credited': total_credited,
        'total_debited': total_debited,
        'total_txns': total_txns,
    })


@login_required
def wallet_balance_api(request):
    wallet = get_or_create_wallet(request.user)
    return JsonResponse({'balance': str(wallet.balance)})