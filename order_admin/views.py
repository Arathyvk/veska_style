import uuid
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings as django_settings
from django.db.models import Q, Sum, Case, When, Value, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce



from product_admin.models import Product, ProductVariant
from category_admin.models import Category
from order_user.models import Order


NON_RETURNABLE_CATEGORIES = [
    'hygiene', 'personalised', 'final_sale',
]


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

    qs = Order.objects.select_related('user').prefetch_related('items').order_by('-created_at')

    if query:
        qs = qs.filter(
            Q(full_name__icontains=query) |
            Q(user__email__icontains=query) |
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(phone__icontains=query) |
            Q(city__icontains=query)
        )

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

    order.status = new_status

    if new_status == 'delivered' and not order.delivered_at:
        order.delivered_at = timezone.now()

    if new_status == 'cancelled' and hasattr(order, 'cancelled_at') and not order.cancelled_at:
        order.cancelled_at = timezone.now()

    order.save()
    
    email_sent = False
    if order.user and order.user.email:
        email_sent = _send_status_update_email(order, old_status, new_status)
        if not email_sent:
            messages.warning(request, f'Order status updated to "{new_status}" but email notification failed.')
        else:
            messages.success(request, f'Order status updated to "{new_status}". An email notification has been sent to {order.user.email}.')
    else:
        messages.success(request, f'Order status updated to "{new_status}". (No email sent - customer email not available)')

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

    # ── compute the real final total ──────────────────────────
    email_total = max(
        subtotal - offer_disc - coupon_disc + shipping - wallet_used,
        0.0
    )
    # ──────────────────────────────────────────────────────────

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
        .prefetch_related('variants', 'images')
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
    ).annotate(
        effective_stock=Case(
            When(variant_stock_sum__gt=0, then='variant_stock_sum'),
            default='stock',
            output_field=IntegerField()
        )
    )

    if stock_filter == 'out':
        qs = qs.filter(effective_stock=0)
    elif stock_filter == 'low':
        qs = qs.filter(effective_stock__gt=0, effective_stock__lte=LOW_STOCK_THRESHOLD)
    elif stock_filter == 'in':
        qs = qs.filter(effective_stock__gt=LOW_STOCK_THRESHOLD)

    sort_mapping = {
        'name':   'name',
        '-name':  '-name',
        'stock':  'effective_stock',
        '-stock': '-effective_stock',
    }
    qs = qs.order_by(sort_mapping.get(sort_param, 'name'))

    all_products = Product.objects.annotate(
        variant_stock_sum=Coalesce(
            Sum('variants__stock'),
            Value(0),
            output_field=IntegerField()
        )
    ).annotate(
        effective_stock=Case(
            When(variant_stock_sum__gt=0, then='variant_stock_sum'),
            default='stock',
            output_field=IntegerField()
        )
    )

    inv_stats = {
        'subtotal':     all_products.count(),
        'listed':       all_products.filter(is_listed=True,  is_blocked=False).count(),
        'unlisted':     all_products.filter(is_listed=False).count(),
        'blocked':      all_products.filter(is_blocked=True).count(),
        'out_of_stock': all_products.filter(effective_stock=0).count(),
        'low_stock':    all_products.filter(
                            effective_stock__gt=0,
                            effective_stock__lte=LOW_STOCK_THRESHOLD
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
    product  = get_object_or_404(Product, pk=product_id)
    variants = product.variants.all().order_by('size')
    images   = product.images.all().order_by('order')
    return render(request, 'inventory_detail.html', {
        'product':   product,
        'variants':  variants,
        'images':    images,
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

    if variant_id:
        variant = get_object_or_404(ProductVariant, pk=variant_id, product=product)
        old = variant.stock
        variant.stock = new_stock
        variant.save(update_fields=['stock'])
        messages.success(request, f'Stock for {product.name} (Size {variant.size}) updated: {old} → {new_stock}.')
    else:
        old = product.stock
        product.stock = new_stock
        product.save(update_fields=['stock'])
        messages.success(request, f'Stock for {product.name} updated: {old} → {new_stock}.')

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