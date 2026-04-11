from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Q, Sum
from django.http import HttpResponse
from weasyprint import HTML

 
from checkout_page.models import Order, OrderItem


def _get_order(request, order_number):
    qs = Order.objects.filter(order_number=order_number)
    if request.user.is_authenticated:
        qs = qs.filter(user=request.user)
    else:
        if not request.session.session_key:
            request.session.create()
        qs = qs.filter(session_key=request.session.session_key)
    return get_object_or_404(qs)
 
 
def _restore_stock(item):
    try:
        if item.product:
            from product_admin.models import ProductVariant
            variant = None
            if item.size:
                variant = ProductVariant.objects.filter(
                    product=item.product, size=item.size
                ).first()
            if variant:
                variant.stock += item.quantity
                variant.save(update_fields=['stock'])
            else:
                item.product.stock += item.quantity
                item.product.save(update_fields=['stock'])
    except Exception:
        pass



def order_success(request, order_number):
    order = _get_order(request, order_number)
    return render(request, 'order_success.html', {'order': order})
 
 
def order_list(request):
    if request.user.is_authenticated:
        orders = Order.objects.filter(user=request.user).prefetch_related('items')
    else:
        if not request.session.session_key:
            request.session.create()
        orders = Order.objects.filter(session_key=request.session.session_key).prefetch_related('items')
 
    q = request.GET.get('q', '').strip()
    if q:
        orders = orders.filter(
            Q(order_number__icontains=q) |
            Q(items__product_name__icontains=q)
        ).distinct()
 
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        orders = orders.filter(status=status_filter)
 
    return render(request, 'order_list.html', {
        'orders':         orders,
        'query':          q,
        'status_filter':  status_filter,
        'status_choices': Order.STATUS_CHOICES,
    })
 
 
def order_detail(request, order_number):
    order = _get_order(request, order_number)
    return render(request, 'order_detail.html', {'order': order})
 

 
@require_POST
def order_cancel(request, order_number):
    order = _get_order(request, order_number)

    if not order.can_cancel:
        messages.error(request, "Order cannot be cancelled.")
        return redirect('order_detail', order_number=order_number)

    reason = request.POST.get('cancel_reason')
    if not reason:
        messages.error(request, "Select a reason.")
        return redirect('order_detail', order_number=order_number)

    for item in order.items.filter(is_cancelled=False):
        _restore_stock(item)
        item.is_cancelled = True
        item.cancel_reason = reason
        item.cancelled_at = timezone.now()
        item.save(update_fields=['is_cancelled', 'cancel_reason', 'cancelled_at'])

    order.status = 'cancelled'
    order.cancel_reason = reason
    order.cancelled_at = timezone.now()
    order.subtotal = 0
    order.total = 0
    order.save()

    messages.success(request, "Order cancelled successfully.")
    return redirect('order_detail', order_number=order_number)
 
 


@require_POST
def order_item_cancel(request, order_number, item_id):
    order = _get_order(request, order_number)

    if not order.can_cancel:
        messages.error(request, "Item cannot be cancelled now.")
        return redirect('order_detail', order_number=order_number)

    item = get_object_or_404(
        OrderItem,
        id=item_id,
        order=order,
        is_cancelled=False
    )

    reason = request.POST.get('cancel_reason')
    if not reason:
        messages.error(request, "Select a reason.")
        return redirect('order_detail', order_number=order_number)


    _restore_stock(item)


    item.is_cancelled = True
    item.cancel_reason = reason
    item.cancelled_at = timezone.now()
    item.save(update_fields=[
        'is_cancelled',
        'cancel_reason',
        'cancelled_at'
    ])


    active_items = order.items.filter(is_cancelled=False)

    if not active_items.exists():

        order.status = 'cancelled'
        order.subtotal = 0
        order.total = 0
    else:

        subtotal = active_items.aggregate(
            total=Sum('line_total')
        )['total'] or 0

        order.subtotal = subtotal
        order.total = subtotal + order.shipping_charge - (order.discount or 0)

    order.save()

    messages.success(request, f"{item.product_name} cancelled.")
    return redirect('order_detail', order_number=order_number)



@require_POST
def order_return(request, order_number):
    order = _get_order(request, order_number)

    if not order.can_return:
        messages.error(request, "Return not allowed.")
        return redirect('order_detail', order_number=order_number)

    reason = request.POST.get('return_reason')
    if not reason:
        messages.error(request, "Select return reason.")
        return redirect('order_detail', order_number=order_number)

    order.status = 'return_requested'
    order.return_reason = reason
    order.return_requested_at = timezone.now()
    order.save(update_fields=[
        'status',
        'return_reason',
        'return_requested_at'
    ])

    messages.success(request, "Return request submitted.")
    return redirect('order_detail', order_number=order_number)
 
 
def order_invoice(request, order_number):
    order = _get_order(request, order_number)
    try:
        html = render(request, 'invoice.html', {'order': order})
        pdf  = HTML(string=html.content.decode('utf-8'),
                    base_url=request.build_absolute_uri('/')).write_pdf()
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="Veska_Invoice_{order.order_number}.pdf"'
        return resp
    except ImportError:
        return render(request, 'invoice.html', {'order': order})
 