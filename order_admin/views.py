import datetime
import traceback

from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings as django_settings
from django.db.models import Q, Sum,Value, IntegerField, Count
from django.db.models.functions import Coalesce
from django.db import transaction
from django.db import transaction as db_tx
from django.contrib.auth.decorators import user_passes_test
from django.utils.timezone import now

from wallet_user.utils import refund_on_return_approval, refund_on_cancellation,refund_on_admin_item_cancel
from product_admin.models import Product, ProductVariant
from category_admin.models import Category
from order_user.models import Order, OrderItem
from order_admin.models import ReturnRequest, RETURN_DAYS
from wallet_user.models import Wallet, WalletTransaction
from coupon_admin.models import Coupon, CouponUsage


NON_RETURNABLE_CATEGORIES = [
    'hygiene', 'personalised', 'final_sale',
]

ADMIN_CANCELLABLE_STATUSES = ['pending', 'confirmed', 'processing']

LOW_STOCK = 5
ORDERS_PER_PAGE      = 20
INVENTORY_PER_PAGE   = 20
ORDER_ITEMS_PER_PAGE = 10
LOW_STOCK_THRESHOLD  = 10 

ORDER_STATUS_CHOICES = [
    ('pending',           'Pending'),
    ('confirmed',         'Confirmed'),
    ('processing',        'Processing'),
    ('shipped',           'Shipped'),
    ('delivered',         'Delivered'),
    ('cancelled',         'Cancelled'),
    ('return_requested',  'Return Requested'),
    ('returned',          'Returned'),
]


STATUS_FLOW = {
    'pending':           ['confirmed', 'cancelled'],
    'confirmed':         ['processing', 'cancelled'],
    'processing':        ['shipped', 'cancelled'],
    'shipped':           ['delivered'],
    'delivered':         ['return_requested'],
    'return_requested':  ['returned', 'delivered'],
    'returned':          [],
    'cancelled':         [],
}


def is_admin(user):
    return user.is_authenticated and user.is_staff


@never_cache
@login_required(login_url='admin_login')
def admin_order_list(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    query         = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    date_from     = request.GET.get('date_from', '').strip()
    date_to       = request.GET.get('date_to', '').strip()
    sort          = request.GET.get('sort', '-created_at').strip()

    qs = Order.objects.select_related('user').prefetch_related('items').order_by('-created_at').distinct()

    if query:
        qs = qs.filter(
            Q(uuid__icontains=query) |  
            Q(full_name__icontains=query) |
            Q(user__email__icontains=query) |
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(phone__icontains=query) |
            Q(city__icontains=query)
        ).distinct()

    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    sort_map = {
        '-created_at': '-created_at',
        'created_at':  'created_at',
        '-total':      '-total',
        'total':       'total',
    }
    qs = qs.order_by(sort_map.get(sort, '-created_at'))

    paginator = Paginator(qs, ORDERS_PER_PAGE)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    current, num_pages = page_obj.number, paginator.num_pages
    visible = {1, num_pages}
    for i in range(max(1, current - 2), min(num_pages, current + 2) + 1):
        visible.add(i)
    page_range, prev_p = [], None
    for p in sorted(visible):
        if prev_p is not None and p - prev_p > 1:
            page_range.append(None)
        page_range.append(p)
        prev_p = p

    filter_qs = request.GET.copy()
    filter_qs.pop('page', None)
    filter_qs = filter_qs.urlencode()

    all_orders = Order.objects.all()

    delivered_revenue = all_orders.filter(
        status='delivered'
    ).aggregate(r=Sum('total'))['r'] or Decimal('0')

    returned_revenue = all_orders.filter(
        status='returned'
    ).aggregate(r=Sum('total'))['r'] or Decimal('0')

    net_revenue = delivered_revenue - returned_revenue

    stats = {
        'total':            all_orders.count(),
        'pending':          all_orders.filter(status='pending').count(),
        'confirmed':        all_orders.filter(status='confirmed').count(),
        'processing':       all_orders.filter(status='processing').count(),
        'shipped':          all_orders.filter(status='shipped').count(),
        'delivered':        all_orders.filter(status='delivered').count(),
        'cancelled':        all_orders.filter(status='cancelled').count(),
        'return_requested': all_orders.filter(status='return_requested').count(),
        'returned':         all_orders.filter(status='returned').count(),
        'revenue':          net_revenue,
    }

    return render(request, 'admin_order_list.html', {
        'orders':            page_obj,
        'query':             query,
        'status_filter':     status_filter,
        'date_from':         date_from,
        'date_to':           date_to,
        'sort':              sort,
        'page_range':        page_range,
        'status_choices':    ORDER_STATUS_CHOICES,
        'excluded_statuses': ['cancelled', 'returned'],
        'filter_qs':         filter_qs,
        'has_filters':       bool(query or status_filter or date_from or date_to or sort != '-created_at'),
        'paginator':         paginator,
        'total_count':       paginator.count,
        'stats':             stats,
    })



@never_cache
@login_required(login_url='admin_login')
def admin_order_detail(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    order = get_object_or_404(
        Order.objects.select_related('user').prefetch_related(
            'items__product',
            'items__variant',
        ),
        uuid=uuid,
    )

    items_qs       = order.items.all()
    paginator      = Paginator(items_qs, ORDER_ITEMS_PER_PAGE)
    items_page_obj = paginator.get_page(request.GET.get('items_page'))

    get_params = request.GET.copy()
    get_params.pop('items_page', None)
    filter_qs  = get_params.urlencode()

    wallet_used     = Decimal(order.wallet_amount_used or 0)
    subtotal        = Decimal(order.subtotal or 0)
    shipping        = Decimal(order.shipping_charge or 0)

    coupon_code     = getattr(order, 'coupon_code', '') or ''
    coupon_discount = Decimal(getattr(order, 'discount_amount', 0) or 0)

    if coupon_discount == 0:
        try:
            usage = order.coupon_usages.select_related('coupon').first()
            if usage:
                coupon_code     = usage.coupon.code
                coupon_discount = Decimal(usage.discount_amount or 0)
        except Exception:
            pass

    offer_discount = Decimal(getattr(order, 'offer_discount', 0) or 0)
    offer_details  = getattr(order, 'offer_details', '') or ''

    final_total = max(
        subtotal - offer_discount - coupon_discount + shipping - wallet_used,
        Decimal('0')
    )

    refund_to_gateway = max(final_total - wallet_used, Decimal('0'))
    wallet_to_restore = wallet_used if wallet_used > 0 else Decimal('0')

    return render(request, 'admin_order_detail.html', {
        'order':             order,
        'items':             items_page_obj.object_list,
        'items_page_obj':    items_page_obj,
        'status_choices':    ORDER_STATUS_CHOICES,
        'filter_qs':         filter_qs,
        'subtotal':          subtotal,
        'shipping':          shipping,
        'offer_discount':    offer_discount,
        'offer_details':     offer_details,
        'coupon_discount':   coupon_discount,
        'coupon_code':       coupon_code,
        'wallet_used':       wallet_used,
        'final_total':       final_total,
        'refund_to_gateway': refund_to_gateway,
        'wallet_to_restore': wallet_to_restore,
        'cancellable_statuses': ADMIN_CANCELLABLE_STATUSES,
    })


@never_cache
@login_required(login_url='admin_login')
@require_POST
def order_update_status(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    order      = get_object_or_404(Order, uuid=uuid)
    new_status = request.POST.get('status', '').strip()

    if new_status not in dict(ORDER_STATUS_CHOICES):
        messages.error(request, 'Invalid status.')
        return redirect('admin_order_detail', uuid=uuid)

    old_status = order.status

    if old_status == new_status:
        messages.warning(request, 'Status is already set to that value.')
        if request.POST.get('next') == 'list':
            return redirect('admin_order_list')
        return redirect('admin_order_detail', uuid=uuid)

    refund_amount = None

    with transaction.atomic():
        order.status = new_status

        if new_status == 'delivered' and not order.delivered_at:
            order.delivered_at = timezone.now()

        if new_status == 'cancelled' and not order.cancelled_at:
            order.cancelled_at = timezone.now()

        order.save()

      
        if new_status == 'cancelled' and old_status != 'cancelled':
            refund_amount = refund_on_cancellation(order)

        elif new_status == 'returned' and old_status != 'returned':
            refund_amount = refund_on_return_approval(order)

    refund_msg = f" ₹{refund_amount} refunded to {order.user.email}'s wallet." \
                 if refund_amount else ''

    if order.user and order.user.email:
        email_sent = _send_status_update_email(order, old_status, new_status)
        if email_sent:
            messages.success(
                request,
                f'Order status updated to "{new_status}".{refund_msg} '
                f'Email sent to {order.user.email}.'
            )
        else:
            messages.warning(
                request,
                f'Order status updated to "{new_status}".{refund_msg} '
                f'(Email notification failed.)'
            )
    else:
        messages.success(request, f'Order status updated to "{new_status}".{refund_msg}')

    if request.POST.get('next') == 'list':
        return redirect('admin_order_list')
    return redirect('admin_order_detail', uuid=uuid)



def _send_status_update_email(order, old_status, new_status):
    STATUS_MESSAGES = {
        'confirmed':        'Your order has been confirmed and is being prepared.',
        'processing':       'Your order is currently being processed.',
        'shipped':          'Great news! Your order has been shipped and is on its way.',
        'delivered':        'Your order has been delivered. We hope you love it!',
        'cancelled':        'Unfortunately, your order has been cancelled. If you paid online, a refund will be processed within 5-7 business days.',
        'return_requested': 'Your return request has been received and is being reviewed.',
        'returned':         'Your return has been processed. Refund will reflect within 5-7 business days.',
    }

    status_msg  = STATUS_MESSAGES.get(new_status, f'Your order status has been updated to: {new_status.replace("_", " ").title()}')
    order_id    = str(order.uuid)[:8].upper()

    customer_name  = getattr(order.user, 'first_name', '') or order.user.email
    old_label      = old_status.replace('_', ' ').title()
    new_label      = new_status.replace('_', ' ').title()
    subtotal       = float(getattr(order, 'subtotal',         0) or 0)
    coupon_disc    = float(getattr(order, 'discount_amount',  0) or 0)
    offer_disc     = float(order.offer_discount or 0)
    shipping       = float(getattr(order, 'shipping_charge',  0) or 0)
    wallet_used    = float(getattr(order, 'wallet_amount_used', 0) or 0)
    coupon_code    = getattr(order, 'coupon_code', '') or ''
    offer_details  = getattr(order, 'offer_details', '') or ''

    email_total = max(
        subtotal - offer_disc - coupon_disc + shipping - wallet_used,
        0.0
    )

    try:
        payment_display = order.get_payment_method_display()
    except AttributeError:
        raw = getattr(order, 'payment_method', 'N/A')
        payment_display = raw.upper() if raw else 'N/A'

    offer_line   = ''
    if offer_disc > 0:
        offer_part = f' ({offer_details})' if offer_details else ''
        offer_line = f'  Offer discount{offer_part}  : -Rs.{offer_disc:.2f}\n'

    coupon_line  = ''
    if coupon_disc > 0:
        coupon_part = f' ({coupon_code})' if coupon_code else ''
        coupon_line = f'  Coupon discount{coupon_part}  : -Rs.{coupon_disc:.2f}\n'

    wallet_line  = ''
    if wallet_used > 0:
        wallet_line = f'  Wallet used       : -Rs.{wallet_used:.2f}\n'

    shipping_display = 'FREE' if shipping == 0 else f'Rs.{shipping:.2f}'

    address_line2      = getattr(order, 'address_line2', '') or ''
    address_line2_part = f', {address_line2}' if address_line2 else ''

    subject = f'Order #{order_id} — Status Updated to {new_label} | Veska'

    body = f"""Hello {customer_name},

Your Veska order status has been updated.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ORDER STATUS UPDATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Order ID   : #{order_id}
  Previous   : {old_label}
  New Status : {new_label}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{status_msg}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ORDER SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Subtotal          : Rs.{subtotal:.2f}
{offer_line}{coupon_line}{wallet_line}  Shipping          : {shipping_display}
  ─────────────────────────────
  Total Paid        : Rs.{email_total:.2f}
  Payment Method    : {payment_display}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DELIVERY ADDRESS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {order.full_name}
  {order.address_line1}{address_line2_part}
  {order.city}, {order.state} - {order.pincode}
  {order.country}
  Phone: {order.phone}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Need help? Contact us at veskaluxury@gmail.com

Thank you for shopping with Veska!
The Veska Team
www.veska.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This is an automated email. Please do not reply directly.
"""

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[order.user.email],
            fail_silently=False,
        )
        print(f'[EMAIL] Status update sent to {order.user.email} for order #{order_id}')
        return True
    except Exception as e:
        print(f'[EMAIL ERROR] Failed to send status update for order #{order_id}: {e}')
        return False


@staff_member_required(login_url='admin:login')
def inventory_list(request):
    qs = (
        Product.objects
        .select_related('category')
        .prefetch_related('variants', 'variants__images')
    )

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(category__name__icontains=q))

    cat_filter = request.GET.get('category', '').strip()
    if cat_filter:
        qs = qs.filter(category__slug=cat_filter) 

    stock_filter = request.GET.get('stock', '').strip()
    status_filter = request.GET.get('status', '').strip()

    if status_filter == 'listed':
        qs = qs.filter(is_listed=True, is_blocked=False)
    elif status_filter == 'unlisted':
        qs = qs.filter(is_listed=False) 
    elif status_filter == 'blocked':
        qs = qs.filter(is_blocked=True)

    sort_param = request.GET.get('sort', 'name').strip()

    qs = qs.annotate(
        variant_stock_sum=Coalesce(
            Sum('variants__stock'),
            Value(0),
            output_field=IntegerField()
        )
    )

    if stock_filter == 'out':
        qs = qs.filter(variant_stock_sum=0)
    elif stock_filter == 'low':
        qs = qs.filter(variant_stock_sum__gt=0, variant_stock_sum__lte=LOW_STOCK_THRESHOLD)
    elif stock_filter == 'in':
        qs = qs.filter(variant_stock_sum__gt=LOW_STOCK_THRESHOLD)

    sort_mapping = {
        'name':   'name',
        '-name':  '-name',
        'stock':  'variant_stock_sum',
        '-stock': '-variant_stock_sum',
    }
    qs = qs.order_by(sort_mapping.get(sort_param, 'name'))

    all_products = Product.objects.annotate(
        variant_stock_sum=Coalesce(
            Sum('variants__stock'),
            Value(0),
            output_field=IntegerField()
        )
    )

    inv_stats = {
        'subtotal':     all_products.count(),
        'listed':       all_products.filter(is_listed=True,  is_blocked=False).count(),
        'unlisted':     all_products.filter(is_listed=False).count(),
        'blocked':      all_products.filter(is_blocked=True).count(),
        'out_of_stock': all_products.filter(variant_stock_sum=0).count(),
        'low_stock':    all_products.filter(
                            variant_stock_sum__gt=0,
                            variant_stock_sum__lte=LOW_STOCK_THRESHOLD
                        ).count(),
    }

    paginator = Paginator(qs, INVENTORY_PER_PAGE)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    get_params = request.GET.copy()
    get_params.pop('page', None)
    filter_qs = get_params.urlencode()

    all_categories = Category.objects.filter(is_active=True).order_by('name')

    has_filters = any([q, cat_filter, stock_filter, status_filter, sort_param != 'name'])

    return render(request, 'admin_inventory.html', {
        'page_obj':       page_obj,
        'products':       page_obj.object_list,   
        'paginator':      paginator,
        'total_count':    paginator.count,
        'inv_stats':      inv_stats,
        'q':              q,
        'cat_filter':     cat_filter,
        'stock_filter':   stock_filter,
        'status_filter':  status_filter,
        'sort':           sort_param,
        'has_filters':    has_filters,
        'all_categories': all_categories,
        'filter_qs':      filter_qs,
        'LOW_STOCK':      LOW_STOCK_THRESHOLD,
    })



@staff_member_required(login_url='admin:login')
def inventory_detail(request, product_id):
    product  = get_object_or_404(
        Product.objects.prefetch_related('variants__images'),
        pk=product_id
        )
    variants = product.variants.all().order_by('size')
    return render(request, 'inventory_detail.html', {
        'product':   product,
        'variants':  variants,
        'LOW_STOCK': LOW_STOCK_THRESHOLD,
    })


@require_POST
@staff_member_required(login_url='admin:login')
def inventory_update_stock(request, product_id):
    product    = get_object_or_404(Product, pk=product_id)
    variant_id = request.POST.get('variant_id', '').strip()
    new_stock  = request.POST.get('stock', '').strip()

    try:
        new_stock = int(new_stock)
        if new_stock < 0:
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, 'Stock must be a non-negative number.')
        return redirect('admin_inventory_detail', product_id=product_id)

    variant = get_object_or_404(ProductVariant, pk=variant_id, product=product)
    old = variant.stock
    variant.stock = new_stock
    variant.save(update_fields=['stock'])
    messages.success(request, f'Stock for {product.name} (Size {variant.size}) updated: {old} → {new_stock}.')
   
    return redirect('admin_inventory_detail', product_id=product_id)


@require_POST
@staff_member_required(login_url='admin:login')
def inventory_toggle_status(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    action  = request.POST.get('action', '').strip()

    if action == 'toggle_listed':
        product.is_listed = not product.is_listed
        product.save(update_fields=['is_listed'])
        messages.success(request, f'"{product.name}" is now {"listed" if product.is_listed else "unlisted"}.')

    elif action == 'toggle_blocked':
        product.is_blocked = not product.is_blocked
        product.save(update_fields=['is_blocked'])
        messages.success(request, f'"{product.name}" has been {"blocked" if product.is_blocked else "unblocked"}.')

    if request.POST.get('next') == 'list':
        return redirect('admin_inventory_list')
    return redirect('admin_inventory_detail', product_id=product_id)


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_cancel_order_item(request, item_id):
    item  = get_object_or_404(OrderItem, pk=item_id)
    order = item.order

    if order.status not in ADMIN_CANCELLABLE_STATUSES:
        messages.error(
            request,
            f"Cannot cancel — order status is '{order.get_status_display()}'. "
            f"Only {', '.join(ADMIN_CANCELLABLE_STATUSES)} orders can have items cancelled."
        )
        return redirect('admin_order_detail', uuid=order.uuid)

    if item.cancel_status != 'none':
        messages.error(request, "This item is already cancelled.")
        return redirect('admin_order_detail', uuid=order.uuid)

    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, "Please provide a cancellation reason.")
        return redirect('admin_order_detail', uuid=order.uuid)

    is_cod     = order.payment_method == 'cod'
    is_paid    = order.payment_status == 'paid'
    will_refund = (not is_cod) and is_paid

    with db_tx.atomic():
        item.cancel_status = 'cancelled'
        item.is_cancelled  = True
        item.cancel_reason = reason
        item.save(update_fields=['cancel_status', 'is_cancelled', 'cancel_reason'])

        if item.variant:
            item.variant.stock += item.quantity
            item.variant.save(update_fields=['stock'])

        refund_amount = Decimal('0.00')
        if will_refund:
            refund_amount = refund_on_admin_item_cancel(order, item)

        all_cancelled = not order.items.filter(cancel_status='none').exists()
        if all_cancelled:
            order.status        = 'cancelled'
            order.cancelled_at  = timezone.now()
            order.cancel_reason = f"All items cancelled by admin. Last reason: {reason}"
            order.save(update_fields=['status', 'cancelled_at', 'cancel_reason'])

            if order.items.count() == 1 and will_refund:
                pass  
            elif all_cancelled and not will_refund and is_cod:
                pass 

    if refund_amount > 0:
        messages.success(
            request,
            f'"{item.product_name}" cancelled. '
            f'₹{refund_amount} refunded to {order.user.email}\'s wallet.'
        )
    elif is_cod:
        messages.success(
            request,
            f'"{item.product_name}" cancelled. '
            f'No refund issued (COD — cash not yet collected).'
        )
    elif not is_paid:
        messages.success(
            request,
            f'"{item.product_name}" cancelled. '
            f'No refund issued (payment not completed).'
        )
    else:
        messages.success(request, f'"{item.product_name}" cancelled successfully.')

    return redirect('admin_order_detail', uuid=order.uuid)


@never_cache
@login_required(login_url='admin_login')
def admin_return_list(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    status_filter = request.GET.get('status', '').strip()
    query = request.GET.get('q', '').strip()

 
    qs = ReturnRequest.objects.select_related(
        'user',
        'order',
        'order_item',
        'order_item__product'
    ).order_by('-created_at')

   
    if status_filter:
        qs = qs.filter(status=status_filter)

 
    if query:
        qs = qs.filter(
            Q(user__email__icontains=query) |
            Q(user__first_name__icontains=query) |
            Q(order__id__icontains=query) |
            Q(order_item__product__name__icontains=query)
        )

    qs = qs.distinct()

    stats = qs.aggregate(
        total=Count('id', distinct=True),
        pending=Count('id', filter=Q(status='pending')),
        approved=Count('id', filter=Q(status='approved')),
        rejected=Count('id', filter=Q(status='rejected')),
    )
 
    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

 
    current = page_obj.number
    num_pages = paginator.num_pages

    visible = {1, num_pages}

    for i in range(current - 2, current + 3):
        if 1 <= i <= num_pages:
            visible.add(i)

    page_range = []
    prev = None

    for p in sorted(visible):
        if prev and p - prev > 1:
            page_range.append(None)
        page_range.append(p)
        prev = p
   
    return render(request, 'admin_return_list.html', {
        'returns': page_obj,
        'stats': stats,
        'status_filter': status_filter,
        'query': query,
        'page_range': page_range,
    })



@never_cache
@login_required(login_url='admin_login')
def admin_return_detail(request, pk):
    if not is_admin(request.user):
        return redirect('admin_login')

    ret = get_object_or_404(
        ReturnRequest.objects.select_related(
            'user',
            'order',
            'order_item',
            'order_item__product',
            'order_item__variant'
        ),
        pk=pk
    )

    proof_images = ret.proof_images.all()
    refund_amount = Decimal("0.00")

    if ret.order_item:
        refund_amount = (
            ret.order_item.line_total
            if ret.order_item.line_total
            else ret.order_item.quantity * ret.order_item.unit_price
        )

        if ret.order.subtotal and ret.order.subtotal > 0:
            total_discount = (
                Decimal(ret.order.offer_discount or 0)
                + Decimal(ret.order.discount_amount or 0)
            )

            if total_discount > 0:
                discount_rate = total_discount / ret.order.subtotal
                item_discount = (
                    refund_amount * discount_rate
                ).quantize(Decimal("0.01"))
                refund_amount = max(
                    refund_amount - item_discount,
                    Decimal("0.00")
                )

        other_active_items = (
            ret.order.items
            .exclude(pk=ret.order_item.pk)
            .filter(cancel_status="none")
        )

        if not other_active_items.exists():
            refund_amount += Decimal(ret.order.shipping_charge or 0)

    internal_notes = []

    if ret.order.delivered_at:
        return_deadline = ret.order.delivered_at + datetime.timedelta(days=RETURN_DAYS)
    else:
        return_deadline = None

    deadline_expired = (
        return_deadline is not None and timezone.now() > return_deadline
    )

    month_start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    user_returns = ReturnRequest.objects.filter(user=ret.user)

    user_stats = {
        'total_orders': ret.user.orders.count() if hasattr(ret.user, 'orders') else 0,
        'total_returns': user_returns.count(),
        'returns_this_month': user_returns.filter(created_at__gte=month_start).count(),
        'is_flagged': getattr(ret.user, 'is_flagged', False),
    }

    category = str(ret.order_item.product.category).lower()

    eligibility_checks = [
        {
            'label': 'Order is delivered',
            'passed': ret.order.status == 'delivered',
        },
        {
            'label': f'Within {RETURN_DAYS}-day return window',
            'passed': not deadline_expired,
        },
        {
            'label': 'Product is in returnable category',
            'passed': category not in NON_RETURNABLE_CATEGORIES,
        },
        {
            'label': 'No previous return for this item',
            'passed': ReturnRequest.objects.filter(
                order_item=ret.order_item,
                status__in=['approved', 'completed']
            ).exclude(pk=ret.pk).count() == 0,
        },
        {
            'label': 'Reason provided',
            'passed': bool(ret.return_reason),
        },
        {
            'label': 'Proof images uploaded',
            'passed': (
                ret.return_reason not in ('defective', 'wrong_item', 'not_as_described')
                or proof_images.exists()
            ),
        },
    ]

    return render(request, 'admin_return_detail.html', {
        'return_request': ret,
        'proof_images': proof_images,
        'internal_notes': internal_notes,
        'return_deadline': return_deadline,
        'deadline_expired': deadline_expired,
        'user_stats': user_stats,
        'eligibility_checks': eligibility_checks,
        'refund_amount': refund_amount,
    })


@never_cache
@login_required(login_url='admin_login')
@require_POST
def admin_return_action(request, pk):
    if not is_admin(request.user):
        return redirect('admin_login')

    ret = get_object_or_404(ReturnRequest, pk=pk)
    action = request.POST.get('action', '').strip()
    reason = request.POST.get('reason', '').strip()
    note = request.POST.get('note', '').strip()
    order = ret.order

    if action == 'approve':
        if ret.status != 'pending':
            messages.error(request, 'This return request is no longer pending.')
            return redirect('admin_return_detail', pk=pk)

        ret.status = 'approved'
        ret.admin_notes = note
        ret.save(update_fields=['status', 'admin_notes'])

        try:
            refund_amount = Decimal('0.00')
            other_active_items = None

            if ret.order_item:
                refund_amount = ret.order_item.line_total if ret.order_item.line_total else (
                    ret.order_item.quantity * ret.order_item.unit_price
                )
                if order.subtotal and order.subtotal > 0:
                    total_discount = (order.offer_discount or Decimal('0')) + (order.discount_amount or Decimal('0'))
                    if total_discount > 0:
                        discount_rate = total_discount / order.subtotal
                        item_discount_share = (refund_amount * discount_rate).quantize(Decimal('0.01'))
                        refund_amount = max(refund_amount - item_discount_share, Decimal('0'))

                other_active_items = order.items.exclude(pk=ret.order_item.pk).filter(cancel_status='none')
                if not other_active_items.exists():
                    shipping_charge = Decimal(order.shipping_charge or 0)
                    refund_amount += shipping_charge
            else:
                refund_amount = order.total

            if refund_amount <= 0:
                messages.warning(request, f'Return #{pk} approved but no refund amount available.')
            else:
                wallet, created = Wallet.objects.get_or_create(user=order.user)
                wallet.credit(
                    amount=refund_amount,
                    reason=WalletTransaction.REASON_RETURN,
                    order=order,
                    description=f'Refund for "{ret.order_item.product_name}" from order #{order.order_number}'
                )
                wallet.refresh_from_db()

                if other_active_items is None or not other_active_items.exists():
                    order.status = 'returned'
                    order.save(update_fields=['status'])

                    if order.coupon_code:
                        try:
                            coupon_obj = Coupon.objects.get(code=order.coupon_code)
                            coupon_obj.times_used = max(0, coupon_obj.times_used - 1)
                            coupon_obj.save(update_fields=['times_used'])
                            CouponUsage.objects.filter(user=order.user, coupon=coupon_obj, order=order).delete()
                        except Coupon.DoesNotExist:
                            pass

                messages.success(
                    request,
                    f'Return #{pk} approved. ₹{refund_amount} refunded to {order.user.email}\'s wallet.'
                )

        except Exception as e:
            traceback.print_exc()
            messages.error(request, f'Return approved but refund failed: {str(e)}')
            
    elif action == 'reject':
        if not reason:
            messages.error(request, 'Please provide a rejection reason.')
            return redirect('admin_return_detail', pk=pk)
            
        ret.status = 'rejected'
        ret.rejection_reason = reason
        ret.admin_notes = note
        ret.save(update_fields=['status', 'rejection_reason', 'admin_notes'])
        messages.success(request, f'Return #{pk} rejected.')

    elif action == 'complete':
        if ret.status != 'approved':
            messages.error(request, 'Return must be approved before completing.')
            return redirect('admin_return_detail', pk=pk)
            
        ret.status = 'completed'
        ret.admin_notes = note
        ret.save(update_fields=['status', 'admin_notes'])
        messages.success(request, f'Return #{pk} completed.')

    else:
        messages.error(request, 'Invalid action.')

    return redirect('admin_return_detail', pk=pk)


@never_cache
@login_required(login_url='admin_login')
@require_POST
def admin_return_add_note(request, pk):
    if not is_admin(request.user):
        return redirect('admin_login')

    note_text = request.POST.get('note', '').strip()

    if note_text:
        messages.success(request, 'Note saved.')
    else:
        messages.error(request, 'Note cannot be empty.')

    return redirect('admin_return_detail', pk=pk)