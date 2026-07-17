from decimal import Decimal
from django.db import transaction
from wallet_user.models import Wallet, WalletTransaction


def get_or_create_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


@transaction.atomic
def refund_on_cancellation(order):
    print("UUID:", order.uuid)
    print("Payment:", order.payment_method)
    print("Status:", order.payment_status)

    if not order or not order.user:
        print("FAILED: order/user missing")
        return None

    if order.payment_method == "cod":
        print("FAILED: COD")
        return None

    is_pre_confirm_cancellation = order.status in {"pending", "confirmed", "processing"}
    is_payment_ready = order.payment_status in {"paid", "pending"}

    if not is_payment_ready and not is_pre_confirm_cancellation:
        print("FAILED: payment not paid")
        return None

    refund_amount = (
        Decimal(str(order.total or 0))
        + Decimal(str(order.wallet_amount_used or 0))
    )

    print("Refund Amount:", refund_amount)

    wallet = get_or_create_wallet(order.user)
    print("Wallet Before:", wallet.balance)

    wallet.credit(
        amount=refund_amount,
        reason=WalletTransaction.REASON_CANCELLATION,
        order=order,
        description=f"Refund for order {order.uuid}",
    )

    wallet.refresh_from_db()

    print("Wallet After:", wallet.balance)
    print("Refund completed")
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
def refund_single_item_cancellation(order, item):
    wallet = get_or_create_wallet(order.user)

    if order.payment_method == 'cod':
        WalletTransaction.objects.create(
            wallet=wallet,
            user=order.user,
            transaction_type=WalletTransaction.CREDIT,
            amount=Decimal('0.00'),
            reason=WalletTransaction.REASON_CANCELLATION,
            order=order,
            reference=str(order.uuid)[:12].upper(),
            description=(
                f'"{item.product_name}" cancelled from order #{order.order_number} '
                f'(Cash on Delivery — no charge was made)'
            ),
        )
        return Decimal('0.00')

    is_pre_confirm_cancellation = order.status in {'pending', 'confirmed', 'processing'}
    is_payment_ready = order.payment_status in {'paid', 'pending'}

    if not is_payment_ready and not is_pre_confirm_cancellation:
        return Decimal('0.00')

    subtotal = Decimal(str(order.subtotal or 0))
    if subtotal <= 0:
        return Decimal('0.00')

    item_line = Decimal(str(item.line_total or 0))

    if item_line <= 0:
        item_line = Decimal(str(item.unit_price)) * Decimal(str(item.quantity))

    total_discount = (
        Decimal(str(order.offer_discount  or 0)) +
        Decimal(str(order.discount_amount or 0))
    )
    discount_rate = total_discount / subtotal if subtotal > 0 else 0
    item_discount_share = (item_line * discount_rate).quantize(Decimal('0.01'))

    shipping_total = Decimal(str(order.shipping_charge or 0))
    shipping_rate = shipping_total / subtotal if subtotal > 0 else 0
    item_shipping_share = (item_line * shipping_rate).quantize(Decimal('0.01'))

    refund_amount = max(
        item_line - item_discount_share + item_shipping_share,
        Decimal('0.00'),
    )

    if refund_amount <= 0:
        WalletTransaction.objects.create(
            wallet=wallet,
            user=order.user,
            transaction_type=WalletTransaction.CREDIT,
            amount=Decimal('0.00'),
            reason=WalletTransaction.REASON_CANCELLATION,
            order=order,
            reference=str(order.uuid)[:12].upper(),
            description=(
                f'"{item.product_name}" cancelled from order #{order.order_number} '
                f'(No refund amount)'
            ),
        )
        return Decimal('0.00')

    wallet.credit(
        amount=refund_amount,
        reason=WalletTransaction.REASON_CANCELLATION,
        order=order,
        description=(
            f'Refund for "{item.product_name}" from order #{order.order_number} '
            f'(item ₹{item_line} − discount ₹{item_discount_share} + shipping ₹{item_shipping_share})'
        ),
    )
    
    print(f"DEBUG: Refunded ₹{refund_amount} to wallet for order {order.order_number}")
    
    return refund_amount

@transaction.atomic
def refund_on_admin_item_cancel(order, item):
    return refund_single_item_cancellation(order, item)