from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.utils import timezone
from django.db.models import Q
from django.http import HttpResponse
from datetime import timedelta
from decimal import Decimal
from django.db import transaction as db_tx

from order_user.models import Order, OrderItem
from return_admin.models import ReturnRequest, RETURN_DAYS, NON_RETURNABLE_CATEGORIES
from product_admin.models import ProductVariant
# from wallet.models import Wallet



NON_RETURNABLE_CATEGORIES = [
    'hygiene','personalised', 'final_sale',
]

TIMELINE_STEPS = [
    ('pending',    'Ordered'),
    ('confirmed',  'Confirmed'),
    ('processing', 'Processing'),
    ('shipped',    'Shipped'),
    ('delivered',  'Delivered'),
]

STATUS_ORDER = [s[0] for s in TIMELINE_STEPS]

CANCEL_REASONS =[
    ('changed_mind',   'Changed my mind'),
    ('wrong_item',     'Orderes wrong item/size'),
    ('found_cheaper',  'Found better price elsewhere'),
    ('delivery_delay', 'Delivery is taking too long'),
    ('payment_issue',  'Payment issue'),
    ('other',          'other'),

]

RETURN_REASONS = [
    ('wrong_size',        'Wrong size received'),
    ('wrong_item',        'Wrong item received'),
    ('defective',         'Defective / damaged product'),
    ('not_as_described',  'Not as described'),
    ('changed_mind',      'Changed my mind'),
    ('quality_issue',     'Quality not as expected'),
    ('other',             'Other'),
]



@login_required
def order_list(request):
    qs = Order.objects.filter(user=request.user).prefetch_related('items','return_requests')

    search_query = request.GET.get('q', '').strip()
    if search_query:
        qs = qs.filter(
            Q(order_number__icontains=search_query) |
            Q(items__product_name__icontains=search_query) |
            Q(status__icontains=search_query) |
            Q(city__icontains=search_query)
        ).distinct()

    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        qs = qs.filter(status=status_filter)

    orders = qs.order_by('-created_at')

    return render(request, 'order_list.html', {
        'orders':         orders,
        'search_query':   search_query,
        'status_filter':  status_filter,
        'status_choices': Order.STATUS_CHOICES,
        'total_orders':   orders.count(),
    })


@never_cache
@login_required(login_url='login')
def order_detail(request, order_number):

    order = get_object_or_404(
        Order.objects.prefetch_related(
            'items__product__images',
            'items__variant',
        ),
        order_number=order_number,
        user=request.user
    )

    current_idx = STATUS_ORDER.index(order.status) if order.status in STATUS_ORDER else -1
    completed_steps = set(STATUS_ORDER[:current_idx])

    item_return_map = {}

    for item in order.items.all():

        existing_return = ReturnRequest.objects.filter(
            order_item=item,
            user=request.user
        ).first()

        category = str(
            item.product.category if item.product and item.product.category else ''
        ).lower()

        is_returnable_category = category not in NON_RETURNABLE_CATEGORIES

        item_return_map[item.pk] = {
            'is_returnable_category': is_returnable_category,
            'existing_return': existing_return,
            'deadline_expired': order.return_deadline_expired,
            'days_left': order.days_left_to_return,
            'can_return': (
                order.status == 'delivered'
                and is_returnable_category
                and not order.return_deadline_expired
                and existing_return is None
            ),
        }

    return render(request, 'order_detail.html', {
        'order': order,
        'items': order.items.all(),
        'timeline_steps': TIMELINE_STEPS,
        'completed_steps': completed_steps,
        'item_return_map': item_return_map,
    })




@login_required
def order_success(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    return render(request, 'order_success.html', {'order': order})


@login_required
def cancel_order(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
 
    if not order.can_cancel:
        messages.error(request, "This order can no longer be cancelled.")
        return redirect('order_detail', order_number=order_number)
 
    if request.method == 'POST':
        reason = request.POST.get('cancel_reason', '').strip()
 
        with db_tx.atomic():
            for item in order.items.filter(status='active'):
                if item.variant:
                    item.variant.stock += item.quantity
                    item.variant.save(update_fields=['stock'])
                item.status       = 'cancelled'
                item.cancel_reason = reason
                item.cancelled_at  = timezone.now()
                item.save()
 
            order.status        = 'cancelled'
            order.cancel_reason = reason
            order.cancelled_at  = timezone.now()
 
            refund_amount = Decimal('0.00')
            if order.payment_method in ('razorpay', 'wallet') and order.payment_status == 'paid':
                refund_amount = order.total
                try:
                    w = Wallet.get_or_create_for_user(request.user)
                    w.credit(refund_amount,
                             description=f"Refund – cancelled order #{order_number}",
                             reason='ORDER_CANCEL', order=order)
                    order.refund_to_wallet = True
                except Exception:
                    pass
 
            order.save()
 
        msg = f"Order #{order_number} cancelled."
        if refund_amount > 0:
            msg += f" ₹{refund_amount} refunded to your wallet."
        messages.success(request, msg)
        return redirect('order_list')
 
    return render(request, 'checkout/cancel_order.html', {
        'order':   order,
        'reasons': CANCEL_REASONS,
    })



@login_required
def cancel_order_item(request, order_number, item_id):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    item  = get_object_or_404(OrderItem, id=item_id, order=order)
 
    if not item.can_cancel:
        messages.error(request, "This item cannot be cancelled.")
        return redirect('order_detail', order_number=order_number)
 
    if request.method == 'POST':
        reason = request.POST.get('cancel_reason', '').strip()
 
        with db_tx.atomic():
            if item.variant:
                item.variant.stock += item.quantity
                item.variant.save(update_fields=['stock'])
 
            item.status       = 'cancelled'
            item.cancel_reason = reason
            item.cancelled_at  = timezone.now()
            item.save()
 
            if order.payment_method in ('razorpay', 'wallet') and order.payment_status == 'paid':
                try:
                    w = Wallet.get_or_create_for_user(request.user)
                    w.credit(item.line_total,
                             description=f"Refund – '{item.product_name}' in #{order_number}",
                             reason='ORDER_CANCEL', order=order)
                    messages.success(request,
                        f"Item cancelled. ₹{item.line_total} refunded to your wallet.")
                except Exception:
                    messages.success(request, "Item cancelled successfully.")
            else:
                messages.success(request, "Item cancelled successfully.")
 
        return redirect('order_detail', order_number=order_number)
 
    return render(request, 'cancel_item.html', {
        'order':   order,
        'item':    item,
        'reasons': CANCEL_REASONS,
    })



@login_required
def return_order(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
 
    if not order.can_return:
        messages.error(request, "This order is not eligible for return.")
        return redirect('order_detail', order_number=order_number)
 
    if order.status == 'return_requested':
        messages.info(request, "Return already submitted. Awaiting admin review.")
        return redirect('order_detail', order_number=order_number)
 
    if request.method == 'POST':
        return_reason = request.POST.get('return_reason', '').strip()
        return_notes  = request.POST.get('return_notes', '').strip()
 
        if not return_reason:
            messages.error(request, "Please select a reason for the return.")
            return render(request, 'return_order.html', {
                'order': order, 'reasons': RETURN_REASONS,
            })
 
        order.status              = 'return_requested'
        order.return_reason       = return_reason
        order.return_notes        = return_notes
        order.return_requested_at = timezone.now()
        order.save()
 
        messages.success(
            request,
            "Return request submitted. Your refund will be credited after admin review."
        )
        return redirect('order_detail', order_number=order_number)
 
    return render(request, 'checkout/return_order.html', {
        'order': order, 'reasons': RETURN_REASONS,
    })



@login_required
def return_request(request, order_number, item_id):

    order = get_object_or_404(
        Order,
        order_number=order_number,
        user=request.user
    )

    order_item = get_object_or_404(
        OrderItem,
        pk=item_id,
        order=order
    )

    if order.status != 'delivered':
        messages.error(request, 'Returns can only be requested for delivered orders.')
        return redirect('order_detail', order_number=order.order_number)

    if not order.delivered_at:
        messages.error(request, 'Delivery date not recorded.')
        return redirect('order_detail', order_number=order.order_number)

    existing_return = ReturnRequest.objects.filter(
        order_item=order_item,
        user=request.user
    ).first()

    category_slug = ''

    if order_item.product and order_item.product.category:
        category_slug = order_item.product.category.slug.lower()

    is_returnable_category = category_slug not in NON_RETURNABLE_CATEGORIES

    return_deadline = order.delivered_at + timedelta(days=RETURN_DAYS)
    deadline_expired = timezone.now() > return_deadline
    days_left = max(0, (return_deadline - timezone.now()).days)

    if request.method == 'POST':

        if existing_return:
            messages.error(request, 'Return already exists for this item.')
            return redirect('return_request', order_number=order.order_number, item_id=item_id)

        if not is_returnable_category:
            messages.error(request, 'Item not eligible for return.')
            return redirect('order_detail', order_number=order.order_number)

        if deadline_expired:
            messages.error(request, 'Return window closed.')
            return redirect('order_detail', order_number=order.order_number)

        return_reason = request.POST.get('return_reason')
        return_notes = request.POST.get('return_notes') or ''
        confirmed = request.POST.get('confirm_conditions') == 'on'

        if not return_reason:
            messages.error(request, 'Select a return reason.')
            return render(request, 'return_request.html', locals())

        if not confirmed:
            messages.error(request, 'Confirm conditions.')
            return render(request, 'return_request.html', locals())

        ReturnRequest.objects.create(
            user=request.user,
            order=order,
            order_item=order_item,
            return_reason=return_reason,
            return_notes=return_notes,
            status='pending',
        )

        messages.success(request, "Return request submitted.")
        return redirect("order_detail", order_number=order.order_number)

    return render(request, 'return_request.html', {
        'order': order,
        'order_item': order_item,
        'existing_return': existing_return,
        'is_returnable_category': is_returnable_category,
        'deadline_expired': deadline_expired,
        'return_deadline': return_deadline,
        'days_left': days_left,
    })


@login_required
def download_invoice(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    items = order.items.all()

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph,
            Spacer, HRFlowable
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT, TA_CENTER
        import io

        buf      = io.BytesIO()
        doc      = SimpleDocTemplate(buf, pagesize=A4,
                       leftMargin=20*mm, rightMargin=20*mm,
                       topMargin=18*mm, bottomMargin=18*mm)
        styles   = getSampleStyleSheet()
        W, _     = A4
        usable_w = W - 40*mm

        def ps(name, **kw):
            return ParagraphStyle(name, **kw)

        s_head   = ps('h', fontSize=9,   fontName='Helvetica-Bold',
                       textColor=colors.HexColor('#2e2925'))
        s_body   = ps('b', fontSize=8.5, fontName='Helvetica',
                       textColor=colors.HexColor('#2e2925'), leading=13)
        s_right  = ps('r', fontSize=8.5, fontName='Helvetica',
                       alignment=TA_RIGHT, textColor=colors.HexColor('#2e2925'))
        s_center = ps('c', fontSize=8,   fontName='Helvetica',
                       alignment=TA_CENTER, textColor=colors.HexColor('#b0a699'))

        TERRA  = colors.HexColor('#b56744')
        LIGHT  = colors.HexColor('#f2ede6')
        BORDER = colors.HexColor('#e0d9d0')
        INK    = colors.HexColor('#2e2925')

        story = []

        ht = Table([[
            Paragraph('<font name="Helvetica-Bold" size="20" color="#2e2925">VESKA</font><br/>'
                      '<font name="Helvetica" size="8" color="#b56744">Fashion · Style · Elegance</font>',
                      styles['Normal']),
            Paragraph(
                f'<font name="Helvetica-Bold" size="14" color="#2e2925">INVOICE</font><br/>'
                f'<font name="Helvetica" size="8" color="#7a6f66">#{order.order_number}</font><br/>'
                f'<font name="Helvetica" size="8" color="#7a6f66">'
                f'{order.created_at.strftime("%d %B %Y")}</font>',
                ps('hr', alignment=TA_RIGHT)
            ),
        ]], colWidths=[usable_w*0.6, usable_w*0.4])
        ht.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        story.append(ht)
        story.append(HRFlowable(width=usable_w, thickness=1.5, color=TERRA, spaceAfter=10))

        bt = Table([
            [Paragraph('<b>Bill To</b>', s_head), Paragraph('<b>Order Info</b>', s_head)],
            [Paragraph(f'{order.full_name}<br/>{order.phone}', s_body),
             Paragraph(f'Order: <b>#{order.order_number}</b>', s_body)],
            [Paragraph(order.address_one_line, s_body),
             Paragraph(f'Date: {order.created_at.strftime("%d %b %Y, %I:%M %p")}', s_body)],
            [Paragraph('', s_body), Paragraph(f'Status: <b>{order.get_status_display()}</b>', s_body)],
            [Paragraph('', s_body), Paragraph(f'Payment: {order.get_payment_method_display()}', s_body)],
        ], colWidths=[usable_w*0.55, usable_w*0.45])
        bt.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),4),
            ('BACKGROUND',(0,0),(-1,0),LIGHT),
        ]))
        story.append(bt)
        story.append(Spacer(1, 10))

        col_w = [usable_w*0.42, usable_w*0.13, usable_w*0.15, usable_w*0.15, usable_w*0.15]
        rows  = [[
            Paragraph('<b>Product</b>', s_head),
            Paragraph('<b>Size</b>',   ps('ch',  alignment=TA_CENTER, fontSize=9, fontName='Helvetica-Bold')),
            Paragraph('<b>Qty</b>',    ps('ch2', alignment=TA_CENTER, fontSize=9, fontName='Helvetica-Bold')),
            Paragraph('<b>Unit Price</b>', ps('rh', alignment=TA_RIGHT, fontSize=9, fontName='Helvetica-Bold')),
            Paragraph('<b>Total</b>',  ps('rh2', alignment=TA_RIGHT, fontSize=9, fontName='Helvetica-Bold')),
        ]]
        for it in items:
            note = ' <font color="#b53333">(cancelled)</font>' if it.status == 'cancelled' else ''
            rows.append([
                Paragraph(f'{it.product_name}{note}', s_body),
                Paragraph(it.size or '—', ps('cc',  alignment=TA_CENTER, fontSize=8.5, fontName='Helvetica')),
                Paragraph(str(it.quantity), ps('ccc', alignment=TA_CENTER, fontSize=8.5, fontName='Helvetica')),
                Paragraph(f'₹{it.unit_price:.2f}', s_right),
                Paragraph(f'₹{it.line_total:.2f}', s_right),
            ])

        item_table = Table(rows, colWidths=col_w, repeatRows=1)
        item_table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),INK),('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('GRID',(0,0),(-1,-1),0.4,BORDER),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,LIGHT]),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ]))
        story.append(item_table)
        story.append(Spacer(1, 8))

        def tot_row(label, value, bold=False):
            fn = 'Helvetica-Bold' if bold else 'Helvetica'
            fs = 9 if bold else 8.5
            return ['', '', '',
                    Paragraph(label, ps(f'l{label}', fontSize=fs, fontName=fn, alignment=TA_RIGHT, textColor=INK)),
                    Paragraph(value, ps(f'v{label}', fontSize=fs, fontName=fn, alignment=TA_RIGHT, textColor=INK))]

        tot_rows = [tot_row('Subtotal', f'₹{order.subtotal:.2f}')]
        if order.discount_amount:
            tot_rows.append(tot_row(f'Discount ({order.coupon_code})', f'−₹{order.discount_amount:.2f}'))
        tot_rows.append(tot_row('Shipping',
            'FREE' if order.shipping_charge == 0 else f'₹{order.shipping_charge:.2f}'))
        tot_rows.append(tot_row('TOTAL', f'₹{order.total:.2f}', bold=True))

        tot_table = Table(tot_rows, colWidths=col_w)
        tot_table.setStyle(TableStyle([
            ('LINEABOVE',(3,len(tot_rows)-1),(-1,len(tot_rows)-1),1,TERRA),
            ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
        ]))
        story.append(tot_table)
        story.append(Spacer(1, 16))
        story.append(HRFlowable(width=usable_w, thickness=0.5, color=BORDER, spaceAfter=8))
        story.append(Paragraph(
            'Thank you for shopping with Veska! '
            'For queries contact support@veska.in · www.veska.in', s_center))

        doc.build(story)
        buf.seek(0)
        response = HttpResponse(buf, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="Veska_Invoice_{order.order_number}.pdf"')
        return response

    except ImportError:
        return _html_invoice_fallback(request, order, items)


def _html_invoice_fallback(request, order, items):
    return render(request, 'invoice_html.html', {'order': order, 'items': items})




def _restore_stock(item: OrderItem):
    try:
        if item.product is None:
            return
        if item.size:
            variant = ProductVariant.objects.filter(
                product=item.product, size=item.size
            ).first()
            if variant:
                variant.stock += item.quantity
                variant.save(update_fields=['stock'])
                return
        item.product.stock += item.quantity
        item.product.save(update_fields=['stock'])
    except Exception:
        pass