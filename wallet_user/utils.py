from decimal import Decimal
from django.db import transaction
from wallet_user.models import Wallet, WalletTransaction


def get_or_create_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


@transaction.atomic
def refund_on_cancellation(order):
   
    if not order or not order.user:
        return None

    if order.payment_method == 'cod':
        return None 

    if order.payment_status != 'paid':
        return None

    refund_amount = (
        Decimal(str(order.total or 0)) +
        Decimal(str(order.wallet_amount_used or 0))
    )
    if refund_amount <= 0:
        return None

    wallet = get_or_create_wallet(order.user)
    wallet.credit(
        amount=refund_amount,
        reason=WalletTransaction.REASON_CANCELLATION,
        order=order,
        description=(
            f"Cancellation refund for order #{order.order_number} "
            f"(₹{order.total} paid + ₹{order.wallet_amount_used or 0} wallet)"
        ),
    )
    print(f"[REFUND][CANCEL] ₹{refund_amount} → {order.user.email}")
    return refund_amount


@transaction.atomic
def refund_on_return_approval(order):
   
    if not order or not order.user:
        return None

    if order.payment_method == 'cod':
        refund_amount = Decimal(str(order.total or 0))
    else:
        if order.payment_status != 'paid':
            return None
        refund_amount = (
            Decimal(str(order.total or 0)) +
            Decimal(str(order.wallet_amount_used or 0))
        )

    if refund_amount <= 0:
        print(f"[REFUND][RETURN] Skipped — amount is {refund_amount}")
        return None

    wallet = get_or_create_wallet(order.user)
    wallet.credit(
        amount=refund_amount,
        reason=WalletTransaction.REASON_RETURN,
        order=order,
        description=(
            f"Return refund for order #{order.order_number} "
            f"via {order.get_payment_method_display()} "
            f"(₹{order.total} + ₹{order.wallet_amount_used or 0} wallet)"
        ),
    )
    print(f"[REFUND][RETURN] ₹{refund_amount} → {order.user.email}")
    return refund_amount


@transaction.atomic
def debit_wallet_for_order(order, amount):
    if not order or not order.user:
        return None
    amount = Decimal(str(amount or 0))
    if amount <= 0:
        return None
    wallet = get_or_create_wallet(order.user)
    wallet.debit(
        amount=amount,
        reason=WalletTransaction.REASON_ORDER,
        order=order,
        description=f"Payment for order #{order.order_number}",
    )
    return amount


@transaction.atomic
def refund_on_admin_item_cancel(order, item):
    """
    Admin cancels one item.
    
    COD   → no refund (cash never collected before delivery)
    Online paid → proportional refund (item share minus discount share)
                  + proportional wallet_amount_used share
    Unpaid online → no refund
    """
    refund_amount = Decimal('0.00')

    is_online_paid = (
        order.payment_method != 'cod'
        and order.payment_status == 'paid'
    )

    if not is_online_paid:
        print(f"[ADMIN_CANCEL] Skipped — COD or unpaid. method={order.payment_method} status={order.payment_status}")
        return Decimal('0.00')

    subtotal = Decimal(str(order.subtotal or 0))
    if subtotal <= 0:
        print(f"[ADMIN_CANCEL] Skipped — subtotal is 0")
        return Decimal('0.00')

    item_line = Decimal(str(item.line_total or 0))

    # Proportional discount share for this item
    total_discount = (
        Decimal(str(order.offer_discount  or 0)) +
        Decimal(str(order.discount_amount or 0))
    )
    discount_rate       = total_discount / subtotal
    item_discount_share = (item_line * discount_rate).quantize(Decimal('0.01'))

    # Proportional wallet share for this item
    wallet_total = Decimal(str(order.wallet_amount_used or 0))
    wallet_rate  = wallet_total / subtotal
    item_wallet_share = (item_line * wallet_rate).quantize(Decimal('0.01'))

    shipping_total = Decimal(str(order.shipping_charge or 0))
    shipping_rate  = shipping_total / subtotal
    item_shipping_share = (item_line * shipping_rate).quantize(Decimal('0.01'))

    refund_amount = max(
        item_line - item_discount_share + item_shipping_share,
        Decimal('0.00'),
    )

    print(f"[ADMIN_CANCEL] item_line={item_line} discount_share={item_discount_share} "
          f"wallet_share={item_wallet_share} shipping_share={item_shipping_share} "
          f"refund_amount={refund_amount}")

    if refund_amount <= 0:
        return Decimal('0.00')

    wallet, _ = Wallet.objects.get_or_create(user=order.user)
    wallet.credit(
        amount      = refund_amount,
        reason      = WalletTransaction.REASON_CANCELLATION,
        order       = order,
        description = (
            f'Admin refund for cancelled item "{item.product_name}" '
            f'from order #{order.order_number} '
            f'(item ₹{item_line} − discount ₹{item_discount_share} + shipping ₹{item_shipping_share})'
        ),
    )
    print(f"[ADMIN_CANCEL] Credited ₹{refund_amount} to {order.user.email}")
    return refund_amount