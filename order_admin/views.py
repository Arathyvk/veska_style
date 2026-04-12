from django.db.models import Q
from django.contrib   import messages
from django.core.paginator import Paginator
from checkout_page.models import Order, OrderItem
from product_admin.models import Product, ProductVariant
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from product_admin.views import is_admin
from django.views.decorators.http import require_POST



@never_cache
@login_required(login_url='admin_login')
def admin_order_list(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    qs = Order.objects.select_related('user').prefetch_related('items').order_by('-created_at')

    query = request.GET.get('q', '').strip()
    if query:
        qs = qs.filter(
            Q(order_number__icontains=query) |
            Q(full_name__icontains=query)    |
            Q(phone__icontains=query)        |
            Q(user__email__icontains=query)  |
            Q(items__product_name__icontains=query)
        ).distinct()

    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        qs = qs.filter(status=status_filter)

    sort = request.GET.get('sort', 'desc')
    qs   = qs.order_by('created_at' if sort == 'asc' else '-created_at')

    paginator = Paginator(qs, 15)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'admin_order_list.html', {
        'page_obj':       page_obj,
        'query':          query,
        'sort':           sort,
        'status_filter':  status_filter,
        'status_choices': Order.STATUS_CHOICES,
        'params_str':     params.urlencode(),
        'total':          paginator.count,
    })



@never_cache
@login_required(login_url='admin_login')
def admin_order_detail(request, order_number):
    if not is_admin(request.user):
        return redirect('admin_login')

    order = get_object_or_404(Order, order_number=order_number)

    if request.method == 'POST':
        new_status = request.POST.get('status', '').strip()
        valid      = [v for v, _ in Order.STATUS_CHOICES]
        if new_status in valid:
            order.status = new_status
            order.save(update_fields=['status'])
            messages.success(request, f'Order #{order.order_number} status updated to "{order.get_status_display()}".')
        else:
            messages.error(request, 'Invalid status selected.')
        return redirect('admin_order_detail', order_number=order_number)

    return render(request, 'admin_order_detail.html', {
        'order':          order,
        'status_choices': Order.STATUS_CHOICES,
    })



@never_cache
@login_required(login_url='admin_login')
def admin_inventory(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    qs = Product.objects.filter(is_active=True).prefetch_related('variants', 'images')

    query = request.GET.get('q', '').strip()
    if query:
        qs = qs.filter(
            Q(name__icontains=query) |
            Q(category__icontains=query)
        )

    stock_filter = request.GET.get('stock', '').strip()
    if stock_filter == 'out':
        qs = [p for p in qs if p.total_stock == 0]
    elif stock_filter == 'low':
        qs = [p for p in qs if 0 < p.total_stock <= 5]
    elif stock_filter == 'ok':
        qs = [p for p in qs if p.total_stock > 5]
    else:
        qs = list(qs)

    sort = request.GET.get('sort', 'name')
    if sort == 'stock_asc':
        qs = sorted(qs, key=lambda p: p.total_stock)
    elif sort == 'stock_desc':
        qs = sorted(qs, key=lambda p: p.total_stock, reverse=True)
    else:
        qs = sorted(qs, key=lambda p: p.name.lower())

    paginator = Paginator(qs, 20)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'admin_inventory.html', {
        'page_obj':     page_obj,
        'query':        query,
        'sort':         sort,
        'stock_filter': stock_filter,
        'params_str':   params.urlencode(),
        'total':        len(qs),
    })




@require_POST
@login_required(login_url='admin_login')
def admin_stock_update(request, pk):
    """Update stock for a specific variant or product base stock."""
    if not is_admin(request.user):
        return JsonResponse({'ok': False, 'msg': 'Forbidden'}, status=403)

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    variant_id = request.POST.get('variant_id')
    if variant_id:
        try:
            variant       = ProductVariant.objects.get(pk=int(variant_id))
            variant.stock = max(0, int(request.POST.get('stock', 0)))
            variant.save(update_fields=['stock'])
            if is_ajax:
                return JsonResponse({'ok': True, 'new_stock': variant.stock,
                                     'total_stock': variant.product.total_stock})
            messages.success(request, 'Variant stock updated.')
        except (ProductVariant.DoesNotExist, ValueError):
            if is_ajax:
                return JsonResponse({'ok': False, 'msg': 'Variant not found'}, status=404)
            messages.error(request, 'Variant not found.')
    else:
        try:
            product       = Product.objects.get(pk=int(pk))
            product.stock = max(0, int(request.POST.get('stock', 0)))
            product.save(update_fields=['stock'])
            if is_ajax:
                return JsonResponse({'ok': True, 'new_stock': product.stock,
                                     'total_stock': product.total_stock})
            messages.success(request, 'Product stock updated.')
        except (Product.DoesNotExist, ValueError):
            if is_ajax:
                return JsonResponse({'ok': False, 'msg': 'Product not found'}, status=404)
            messages.error(request, 'Product not found.')

    return redirect(request.POST.get('next', 'admin_inventory'))