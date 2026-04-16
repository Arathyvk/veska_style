from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Q, Sum, F
from django.utils import timezone

from order_user.models import Order, OrderItem

from product_admin.models import Product, ProductVariant
from category_admin.models import Category



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




@staff_member_required(login_url='admin:login')
def admin_order_list(request):
    qs = (
        Order.objects
        .select_related('user')
        .prefetch_related('items')
        .order_by('-created_at')
    )

    q = request.GET.get('q', '').strip()
    if q: 
        qs = qs.filter(
            Q(order_number__icontains=q) |
            Q(full_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(user__email__icontains=q) |
            Q(user__username__icontains=q) |
            Q(city__icontains=q) |
            Q(items__product_name__icontains=q)
        ).distinct()

    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        qs = qs.filter(status=status_filter)

    date_from = request.GET.get('date_from', '').strip()
    date_to   = request.GET.get('date_to',   '').strip()
    if date_from:
        try:
            from datetime import datetime
            qs = qs.filter(created_at__date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import datetime
            qs = qs.filter(created_at__date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
        except ValueError:
            pass

    sort = request.GET.get('sort', '-created_at')
    allowed_sorts = {
        '-created_at': '-created_at',
        'created_at':  'created_at',
        '-total':      '-total',
        'total':       'total',
        'order_number': 'order_number',
    }
    qs = qs.order_by(allowed_sorts.get(sort, '-created_at'))

    all_orders = Order.objects.all()
    stats = {
        'total':     all_orders.count(),
        'pending':   all_orders.filter(status__in=['pending', 'confirmed', 'processing']).count(),
        'shipped':   all_orders.filter(status='shipped').count(),
        'delivered': all_orders.filter(status='delivered').count(),
        'cancelled': all_orders.filter(status='cancelled').count(),
        'revenue':   all_orders.filter(status='delivered').aggregate(s=Sum('total'))['s'] or 0,
    }

    has_filters = any([q, status_filter, date_from, date_to])

    paginator = Paginator(qs, ORDERS_PER_PAGE)
    page_num  = request.GET.get('page', 1)
    try:
        page_num = int(page_num)
    except (ValueError, TypeError):
        page_num = 1
    page_obj = paginator.get_page(page_num)

    get = request.GET.copy()
    get.pop('page', None)
    filter_qs = get.urlencode()

    return render(request, 'admin_order_list.html', {
        'page_obj':        page_obj,
        'orders':          page_obj.object_list,
        'paginator':       paginator,
        'total_count':     paginator.count,
        'stats':           stats,
        'q':               q,
        'status_filter':   status_filter,
        'date_from':       date_from,
        'date_to':         date_to,
        'sort':            sort,
        'has_filters':     has_filters,
        'status_choices':  ORDER_STATUS_CHOICES,
        'filter_qs':       filter_qs,
    })


@staff_member_required(login_url='admin:login')
def order_detail(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    # Paginate items inside a single order (admins may need to browse long orders).
    items_qs = order.items.all().order_by('id')

    paginator = Paginator(items_qs, ORDER_ITEMS_PER_PAGE)
    page_num = request.GET.get('items_page', 1)
    try:
        page_num = int(page_num)
    except (ValueError, TypeError):
        page_num = 1

    items_page_obj = paginator.get_page(page_num)

    get = request.GET.copy()
    get.pop('items_page', None)
    filter_qs = get.urlencode()

    allowed_statuses = STATUS_FLOW.get(order.status, [])

    return render(request, 'admin_order_detail.html', {
        'order':            order,
        'items':            items_page_obj.object_list,
        'items_page_obj':  items_page_obj,
        'items_paginator':  paginator,
        'filter_qs':        filter_qs,
        'allowed_statuses': allowed_statuses,
        'status_choices':   ORDER_STATUS_CHOICES,
        'status_labels':    dict(ORDER_STATUS_CHOICES),
    })


@require_POST
@staff_member_required(login_url='admin:login')
def order_update_status(request, order_number):
    order      = get_object_or_404(Order, order_number=order_number)
    new_status = request.POST.get('status', '').strip()

    valid_statuses = [s[0] for s in ORDER_STATUS_CHOICES]
    if new_status not in valid_statuses:
        messages.error(request, 'Invalid status selected.')
        return redirect('admin_order_detail', order_number=order_number)

    old_status  = order.get_status_display()
    order.status = new_status

    if new_status == 'cancelled' and not order.cancelled_at:
        order.cancelled_at  = timezone.now()
        order.cancel_reason = request.POST.get('cancel_reason', '').strip()
        for item in order.items.filter(status='active'):
            _restore_stock(item)
            item.status       = 'cancelled'
            item.cancelled_at = timezone.now()
            item.save(update_fields=['status', 'cancelled_at'])

    order.save(update_fields=['status', 'cancelled_at', 'cancel_reason', 'updated_at'])

    messages.success(
        request,
        f'Order #{order.order_number} status changed from '
        f'{old_status} → {order.get_status_display()}.'
    )
    next_url = request.POST.get('next', '')
    if next_url == 'list':
        return redirect('admin_order_list')
    return redirect('admin_order_detail', order_number=order_number)


def _restore_stock(item):
    try:
        if item.product is None:
            return
        if item.size:
            variant = ProductVariant.objects.filter(
                product=item.product, size=item.size
            ).first()
            if variant:
                variant.stock = F('stock') + item.quantity
                variant.save(update_fields=['stock'])
                return
        item.product.stock = F('stock') + item.quantity
        item.product.save(update_fields=['stock'])
    except Exception:
        pass




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

    # ── Paginate
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