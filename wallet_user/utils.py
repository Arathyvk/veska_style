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

    if order.payment_method == "cod":
        return None

    is_pre_confirm_cancellation = order.status in {"pending", "confirmed", "processing"}
    # consider orders where payment was captured (paid_at) even if payment_status
    # might be missing or inconsistent. This helps credit refunds when the
    # payment was actually completed.
    is_payment_ready = (order.payment_status in {"paid", "pending"}) or bool(getattr(order, 'paid_at', None))

    if not is_payment_ready and not is_pre_confirm_cancellation:
        # skip refund: no payment captured and not a pre-confirm cancellation
        print(f"refund_on_cancellation: skipped for order={order.pk}, payment_status={order.payment_status}, paid_at={getattr(order, 'paid_at', None)}, status={order.status}")
        return None

    refund_amount = (
        Decimal(str(order.total or 0))
        + Decimal(str(order.wallet_amount_used or 0))
    )


    wallet = get_or_create_wallet(order.user)
    wallet.credit(
        amount=refund_amount,
        reason=WalletTransaction.REASON_CANCELLATION,
        order=order,
        description=f"Refund for order {order.uuid}",
    )

    wallet.refresh_from_db()
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
            transaction_type=WalletTransaction.CREDIT,
            amount=Decimal('0.00'),
            reason=WalletTransaction.REASON_CANCELLATION,
            order=order,
            description=(
                f'"{item.product_name}" cancelled from order #{order.order_number} '
                f'(Cash on Delivery — no charge was made)'
            ),
        )
        return Decimal('0.00')

    is_pre_confirm_cancellation = order.status in {'pending', 'confirmed', 'processing'}
    is_payment_ready = (order.payment_status in {'paid', 'pending'}) or bool(getattr(order, 'paid_at', None))

    if not is_payment_ready and not is_pre_confirm_cancellation:
        print(f"refund_single_item_cancellation: skipped for order={order.pk}, payment_status={order.payment_status}, paid_at={getattr(order, 'paid_at', None)}, status={order.status}")
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
            transaction_type=WalletTransaction.CREDIT,
            amount=Decimal('0.00'),
            reason=WalletTransaction.REASON_CANCELLATION,
            order=order,
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
    return refund_amount

@transaction.atomic
def refund_on_admin_item_cancel(order, item):
    return refund_single_item_cancellation(order, item)