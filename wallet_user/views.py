from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator

from wallet_user.models import WalletTransaction
from wallet_user.utils import get_or_create_wallet
  



@login_required
def wallet_dashboard(request):
    wallet = get_or_create_wallet(request.user)
    transactions = wallet.transactions.select_related('order').all()
    txn_filter = request.GET.get('filter', 'all')
    if txn_filter == 'credit':
        transactions = transactions.filter(transaction_type=WalletTransaction.CREDIT)
    elif txn_filter == 'debit':
        transactions = transactions.filter(transaction_type=WalletTransaction.DEBIT)

    paginator = Paginator(transactions, 5)
    txn_page = paginator.get_page(request.GET.get('page', 1))

    credit_txns = wallet.transactions.filter(transaction_type=WalletTransaction.CREDIT)
    debit_txns = wallet.transactions.filter(transaction_type=WalletTransaction.DEBIT)

    total_credited = sum(t.amount for t in credit_txns)
    total_debited = sum(t.amount for t in debit_txns)
    total_txns = wallet.transactions.count()

    transaction_summary = {
        'total_credits': total_credited,
        'total_debits': total_debited,
        'cancellation_refunds': credit_txns.filter(reason=WalletTransaction.REASON_CANCELLATION).count(),
        'return_refunds': credit_txns.filter(reason=WalletTransaction.REASON_RETURN).count(),
        'order_payments': debit_txns.filter(reason=WalletTransaction.REASON_ORDER).count(),
        'referral_bonuses': credit_txns.filter(reason=WalletTransaction.REASON_REFERRAL).count(),
        'welcome_bonuses': credit_txns.filter(reason=WalletTransaction.REASON_WELCOME).count(),
    }

    return render(request, 'wallet_dashboard.html', {
        'wallet': wallet,
        'transactions': txn_page,
        'txn_filter': txn_filter,
        'total_credited': total_credited,
        'total_debited': total_debited,
        'total_txns': total_txns,
        'transaction_summary': transaction_summary,
    })

@login_required
def wallet_balance_api(request):
    wallet = get_or_create_wallet(request.user)
    return JsonResponse({'balance': str(wallet.balance)})