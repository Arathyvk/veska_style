import uuid
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


from product_admin.models import Product, ProductVariant
from category_admin.models import Category
from order_user.models import Order

NON_RETURNABLE_CATEGORIES = [
    'hygiene', 'personalised', 'final_sale',
]

ORDERS_PER_PAGE    = 20
INVENTORY_PER_PAGE = 20
ORDER_ITEMS_PER_PAGE = 10
LOW_STOCK_THRESHOLD = 5

ORDER_STATUS_CHOICES = [
    ('pending',    'Pending'),
    ('confirmed',  'Confirmed'),
    ('processing', 'Processing'),
    ('shipped',    'Shipped'),
    ('delivered',  'Delivered'),
    ('cancelled',  'Cancelled'),
    ('return_requested', 'Return Requested'),
    ('returned',   'Returned'),
]

STATUS_FLOW = {
    'pending':    ['confirmed', 'cancelled'],
    'confirmed':  ['processing', 'cancelled'],
    'processing': ['shipped', 'cancelled'],
    'shipped':    ['delivered'],
    'delivered':  ['return_requested'],
    'return_requested': ['returned', 'delivered'],
    'returned':   [],
    'cancelled':  [],
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
            Q(order_number__icontains=query) |
            Q(user__email__icontains=query) |
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query)  |
            Q(user__address_line1__icontains=query) |
            Q(user__address_line2__icontains=query) 
        )
        
    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
 
    sort_map = {
        '-created_at': '-created_at',
        'created_at': 'created_at',
        '-total': '-total',
        'total': 'total',
    }
    qs = qs.order_by(sort_map.get(sort, '-created_at'))
 
    paginator = Paginator(qs, ORDERS_PER_PAGE)
    page_obj  = paginator.get_page(request.GET.get('page', 1))
 
    current, num_pages = page_obj.number, paginator.num_pages
    visible = set([1, num_pages])
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
    stats = {
        'total': all_orders.count(),
        'pending': all_orders.filter(status='pending').count(),
        'confirmed': all_orders.filter(status='confirmed').count(),
        'processing': all_orders.filter(status='processing').count(),
        'shipped': all_orders.filter(status='shipped').count(),
        'delivered': all_orders.filter(status='delivered').count(),
        'cancelled': all_orders.filter(status='cancelled').count(),
        'return_requested': all_orders.filter(status='return_requested').count(),
        'returned': all_orders.filter(status='returned').count(),
        'revenue': all_orders.aggregate(total_revenue=Sum('total'))['total_revenue'] or 0,
    }
 
    return render(request, 'admin_order_list.html', {
        'orders':        page_obj,
        'query':         query,
        'status_filter': status_filter,
        'date_from':     date_from,
        'date_to':       date_to,
        'sort':          sort,
        'page_range':    page_range,
        'status_choices': ORDER_STATUS_CHOICES,
        'excluded_statuses': ['cancelled', 'returned'],
        'filter_qs':      filter_qs,
        'has_filters':    bool(query or status_filter or date_from or date_to or sort != '-created_at'),
        'paginator':      paginator,
        'total_count':    paginator.count,
        'stats':          stats,
    })
 
 
@never_cache
@login_required(login_url='admin_login')
def order_detail(request, uuid):

    if not is_admin(request.user):
        return redirect('admin_login')

    order = get_object_or_404(
        Order.objects.select_related('user').prefetch_related(
            'items__product',
            'items__variant'
        ),
        uuid=uuid
    )

    items_qs = order.items.all()
    paginator = Paginator(items_qs, ORDER_ITEMS_PER_PAGE)
    page_number = request.GET.get('items_page')
    items_page_obj = paginator.get_page(page_number)

    get_params = request.GET.copy()
    get_params.pop('items_page', None)
    filter_qs = get_params.urlencode()

    context = {
        'order': order,
        'items': items_page_obj.object_list,
        'items_page_obj': items_page_obj,
        'status_choices': ORDER_STATUS_CHOICES,
        'filter_qs': filter_qs,
    }

    return render(request,'admin_order_detail.html',context)
 


@never_cache
@login_required(login_url='admin_login')
@require_POST
def order_update_status(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    order      = get_object_or_404(Order, uuid=uuid)
    new_status = request.POST.get('status', '').strip()

    valid = dict(ORDER_STATUS_CHOICES).keys()
    if new_status not in valid:
        messages.error(request, 'Invalid status.')
        return redirect('admin_order_detail', uuid=uuid)

    old_status = order.status

    # Don't update or email if status hasn't changed
    if old_status == new_status:
        messages.warning(request, 'Status is already set to that value.')
        next_url = request.POST.get('next', '')
        if next_url == 'list':
            return redirect('admin_order_list')
        return redirect('admin_order_detail', uuid=uuid)

    order.status = new_status

    if new_status == 'delivered' and not order.delivered_at:
        order.delivered_at = timezone.now()

    if new_status == 'cancelled' and hasattr(order, 'cancelled_at') and not order.cancelled_at:
        order.cancelled_at = timezone.now()

    order.save()
    messages.success(request, f'Order status updated to "{new_status}".')

    # Send email — only if user exists and has email
    if order.user and order.user.email:
        email_sent = _send_status_update_email(order, old_status, new_status)
        if not email_sent:
            messages.warning(request, 'Status updated but email notification failed.')

    next_url = request.POST.get('next', '')
    if next_url == 'list':
        return redirect('admin_order_list')
    return redirect('admin_order_detail', uuid=uuid)


def _send_status_update_email(order, old_status, new_status):
    """
    Send order status update email to the customer.
    Returns True if sent successfully, False otherwise.
    """

    STATUS_MESSAGES = {
        'confirmed':         'Your order has been confirmed and is being prepared.',
        'processing':        'Your order is currently being processed.',
        'shipped':           'Great news! Your order has been shipped and is on its way.',
        'delivered':         'Your order has been delivered. We hope you love it!',
        'cancelled':         'Unfortunately, your order has been cancelled. If you paid online, a refund will be processed within 5-7 business days.',
        'return_requested':  'Your return request has been received and is being reviewed.',
        'returned':          'Your return has been processed. Refund will reflect within 5-7 business days.',
    }

    status_msg = STATUS_MESSAGES.get(
        new_status,
        f'Your order status has been updated to: {new_status.replace("_", " ").title()}'
    )

    # Safe order ID display — first 8 chars of UUID uppercased
    order_id = str(order.uuid)[:8].upper()

    # Safe field access with fallbacks
    customer_name   = getattr(order.user, 'first_name', '') or order.user.email
    old_label       = old_status.replace('_', ' ').title()
    new_label       = new_status.replace('_', ' ').title()
    subtotal        = getattr(order, 'subtotal', 0) or 0
    discount        = getattr(order, 'discount_amount', 0) or 0
    shipping        = getattr(order, 'shipping_charge', 0) or 0
    wallet_used     = getattr(order, 'wallet_amount_used', 0) or 0
    total           = getattr(order, 'total', 0) or 0
    coupon_code     = getattr(order, 'coupon_code', '') or ''

    # Payment method — safe display
    try:
        payment_display = order.get_payment_method_display()
    except AttributeError:
        payment_method_raw = getattr(order, 'payment_method', 'N/A')
        payment_display = payment_method_raw.upper() if payment_method_raw else 'N/A'

    # Build discount line only if discount exists
    discount_line = ''
    if discount and float(discount) > 0:
        coupon_part = f' ({coupon_code})' if coupon_code else ''
        discount_line = f'Coupon{coupon_part}  : -Rs.{float(discount):.2f}\n'

    # Build wallet line only if wallet was used
    wallet_line = ''
    if wallet_used and float(wallet_used) > 0:
        wallet_line = f'Wallet Used       : -Rs.{float(wallet_used):.2f}\n'

    # Shipping display
    shipping_display = 'FREE' if not shipping or float(shipping) == 0 else f'Rs.{float(shipping):.2f}'

    # Address line 2 is optional
    address_line2 = getattr(order, 'address_line2', '')
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
  Subtotal          : Rs.{float(subtotal):.2f}
{discount_line}{wallet_line}  Shipping          : {shipping_display}
  ─────────────────────────────
  Total Paid        : Rs.{float(total):.2f}
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

Need help? Reply to this email or contact us at veskaluxury@gmail.com

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
            fail_silently=False,  # raise error so we can log/warn
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
        .order_by('name')
    )

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(category__name__icontains=q)
        )

    cat_filter = request.GET.get('category', '').strip()
    if cat_filter:
        qs = qs.filter(category__slug=cat_filter)

    stock_filter = request.GET.get('stock', '').strip()
    if stock_filter == 'out':
        qs = qs.filter(stock=0).exclude(
            variants__stock__gt=0
        )
    elif stock_filter == 'low':
        from django.db.models import ExpressionWrapper, IntegerField
        qs_ids = []
        for p in qs:
            if 0 < p.effective_stock <= LOW_STOCK_THRESHOLD:
                qs_ids.append(p.pk)
        qs = qs.filter(pk__in=qs_ids)
    elif stock_filter == 'in':
        qs_ids = [p.pk for p in qs if p.effective_stock > 0]
        qs = qs.filter(pk__in=qs_ids)

    status_filter = request.GET.get('status', '').strip()
    if status_filter == 'listed':
        qs = qs.filter(is_listed=True, is_blocked=False)
    elif status_filter == 'unlisted':
        qs = qs.filter(is_listed=False)
    elif status_filter == 'blocked':
        qs = qs.filter(is_blocked=True)

    sort = request.GET.get('sort', 'name')
    sort_map = {
        'name':    'name',
        '-name':   '-name',
        'stock':   'stock',
        '-stock':  '-stock',
        'price':   'price',
        '-price':  '-price',
    }
    qs = qs.order_by(sort_map.get(sort, 'name'))

    all_products = Product.objects.all()
    inv_stats = {
        'total': all_products.count(),
        'listed': all_products.filter(is_active=True).count(),
        'unlisted': all_products.filter(is_active=False).count(),
        'blocked': 0,

        'out_of_stock': all_products.filter(stock=0).count(),

        'low_stock': all_products.filter(
            stock__gt=0,
            stock__lte=LOW_STOCK_THRESHOLD
        ).count(),
}

    has_filters = any([q, cat_filter, stock_filter, status_filter])

    paginator = Paginator(qs, INVENTORY_PER_PAGE)
    page_num  = request.GET.get('page', 1)
    try:
        page_num = int(page_num)
    except (ValueError, TypeError):
        page_num = 1
    page_obj = paginator.get_page(page_num)

    get = request.GET.copy()
    get.pop('page', None)
    filter_qs = get.urlencode()

    all_categories = Category.objects.filter(is_active=True).order_by('name')

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
        'sort':           sort,
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
        'product':  product,
        'variants': variants,
        'images':   images,
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
        old     = variant.stock
        variant.stock = new_stock
        variant.save(update_fields=['stock'])
        messages.success(
            request,
            f'Stock for {product.name} (Size {variant.size}) updated: {old} → {new_stock}.'
        )
    else:
        old = product.stock
        product.stock = new_stock
        product.save(update_fields=['stock'])
        messages.success(
            request,
            f'Stock for {product.name} updated: {old} → {new_stock}.'
        )

    return redirect('admin_inventory_detail', product_id=product_id)


@require_POST
@staff_member_required(login_url='admin:login')
def inventory_toggle_status(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    action  = request.POST.get('action', '').strip()

    if action == 'toggle_listed':
        product.is_listed = not product.is_listed
        product.save(update_fields=['is_listed'])
        status = 'listed' if product.is_listed else 'unlisted'
        messages.success(request, f'"{product.name}" is now {status}.')

    elif action == 'toggle_blocked':
        product.is_blocked = not product.is_blocked
        product.save(update_fields=['is_blocked'])
        status = 'blocked' if product.is_blocked else 'unblocked'
        messages.success(request, f'"{product.name}" has been {status}.')

    next_url = request.POST.get('next', 'detail')
    if next_url == 'list':
        return redirect('admin_inventory_list')
    return redirect('admin_inventory_detail', product_id=product_id)


