from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Q
from django.http import HttpResponse
from datetime import timedelta
from decimal import Decimal
from django.db import transaction as db_tx
from order_user.order_email import send_order_confirmation


from order_user.models import Order, OrderItem
from return_admin.models import ReturnRequest, RETURN_DAYS, NON_RETURNABLE_CATEGORIES
from product_admin.models import ProductVariant
from wallet_user.models import Wallet



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

CANCEL_REASONS = [
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


@login_required(login_url='login')
def order_detail(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)
    items = order.items.all()

    subtotal        = Decimal(order.subtotal or 0)
    shipping        = Decimal(order.shipping_charge or 0)
    coupon_discount = Decimal(order.discount_amount or 0)
    coupon_code     = getattr(order, 'coupon_code', '') or ''
    offer_discount  = Decimal(getattr(order, 'offer_discount', 0) or 0)
    offer_details   = getattr(order, 'offer_details', '') or ''
    wallet_used     = Decimal(order.wallet_amount_used or 0)

    final_total = max(
        subtotal - offer_discount - coupon_discount + shipping - wallet_used,
        Decimal('0')
    )

    return render(request, 'order_detail.html', {
        'order':            order,
        'items':            items,
        'steps':            TIMELINE_STEPS,
        'subtotal':         subtotal,
        'shipping':         shipping,
        'coupon_discount':  coupon_discount,
        'coupon_code':      coupon_code,
        'offer_discount':   offer_discount,
        'offer_details':    offer_details,
        'wallet_used':      wallet_used,
        'final_total':      final_total,
    })

@login_required
def order_success(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)
    session_key = f"order_confirmed_{uuid}"
    if not request.session.get(session_key):
        send_order_confirmation(order)          
        request.session[session_key] = True
    return render(request, 'order_success.html', {'order': order})


@login_required
def cancel_order(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)
 
    if not order.can_cancel:
        messages.error(request, "This order can no longer be cancelled.")
        return redirect('order_detail', uuid=order.uuid)
 
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
            if order.payment_method in ('paypal', 'wallet') and order.payment_status == 'paid':
                refund_amount = order.total
                try:
                    w = Wallet.get_or_create_for_user(request.user)
                    w.credit(refund_amount,
                             description=f"Refund – cancelled order #{uuid}",
                             reason='ORDER_CANCEL', order=order)
                    order.refund_to_wallet = True
                except Exception:
                    pass
 
            order.save()
 
        msg = f"Order #{uuid} cancelled."
        if refund_amount > 0:
            msg += f" ₹{refund_amount} refunded to your wallet."
        messages.success(request, msg)
        return redirect('order_list')
 
    return render(request, 'cancel_order.html', {
        'order':   order,
        'reasons': CANCEL_REASONS,
    })



@require_POST
@login_required(login_url='login')
def cancel_order_item(request, item_id):
    item = get_object_or_404(OrderItem, pk=item_id, order__user=request.user)
 
    if item.cancel_status != 'none':
        messages.error(request, 'This item has already been cancelled or a request is pending.')
        return redirect('order_detail', uuid=item.order.uuid)
 
    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, 'Please provide a cancellation reason.')
        return redirect('order_detail', uuid=item.order.uuid)
 
    with db_tx.atomic():
        item.cancel_status = 'cancelled'
        item.cancel_reason = reason
        item.save(update_fields=['cancel_status', 'cancel_reason'])
 
        if item.variant:
            item.variant.stock += item.quantity
            item.variant.save(update_fields=['stock'])
        elif item.product:
            item.product.stock += item.quantity
            item.product.save(update_fields=['stock'])
 
        order = item.order
        if not order.items.filter(cancel_status='none').exists():
            order.status = 'cancelled'
            order.save(update_fields=['status'])
 
    messages.success(request, 'Item cancelled successfully.')
    return redirect('order_detail', uuid=item.order.uuid)


@login_required
def return_order(request, uuid):
    order = get_object_or_404(
        Order,
        uuid = uuid,
        user =request.user
    )

    if not order.can_return:
        messages.error(request,"This order is not eligible for return. ")
        return redirect('order_detail', uuid = order.uuid)
    
    returnable_items = []

    for item in order.items.all():

        existing_return = ReturnRequest.objects.filter(
            order_item=item,
            user=request.user

        ).first()
        
        item.return_request = existing_return

        returnable_items.append(item)

    return_deadline = order.delivered_at + timedelta(days=RETURN_DAYS)    

    days_left = max(
        0,
        (return_deadline  - timezone.now()).days

    )

    return render(request, 'return_order.html',{
        'order' : order,
        'returnable_items' : returnable_items,
        'return_deadline ' : return_deadline.astimezone,
        'days_left' : days_left,
    })


@login_required
def return_request(request, uuid, item_id):

    order = get_object_or_404(
        Order,
        uuid=uuid,
        user=request.user
    )

    order_item = get_object_or_404(
        OrderItem,
        pk=item_id,
        order=order
    )

    if order.status != 'delivered':
        messages.error(request, 'Returns can only be requested for delivered orders.')
        return redirect('order_detail', uuid=order.uuid)

    if not order.delivered_at:
        messages.error(request, 'Delivery date not recorded.')
        return redirect('order_detail', uuid=order.uuid)

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
            return redirect('return_request', uuid=order.uuid, item_id=item_id)

        if not is_returnable_category:
            messages.error(request, 'Item not eligible for return.')
            return redirect('order_detail', uuid=order.uuid)

        if deadline_expired:
            messages.error(request, 'Return window closed.')
            return redirect('order_detail', uuid=order.uuid)

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
        return redirect("order_detail", uuid=order.uuid)

    return render(request, 'return_request.html', {
        'order': order,
        'order_item': order_item,
        'existing_return': existing_return,
        'is_returnable_category': is_returnable_category,
        'deadline_expired': deadline_expired,
        'return_deadline': return_deadline,
        'days_left': days_left,
        'reasons': RETURN_REASONS,
    })


@login_required
def return_order_redirect(request, short_id):
    orders = Order.objects.filter(
        uuid__startswith=short_id.upper(),
        user=request.user
    )
    if orders.exists():
        return redirect('return_order', uuid=orders.first().uuid)
    else:
        messages.error(request, "Order not found")
        return redirect('order_list')
    

@login_required
def download_invoice(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)
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

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                       leftMargin=20*mm, rightMargin=20*mm,
                       topMargin=18*mm, bottomMargin=18*mm,
                       title=f"Invoice_{order.uuid}")
        
        styles = getSampleStyleSheet()
        W, _ = A4
        usable_w = W - 40*mm

        def ps(name, **kw):
            return ParagraphStyle(name, **kw)

        WHITE = colors.HexColor('#FFFFFF')
        LIGHT_GRAY = colors.HexColor('#F5F5F5')
        MEDIUM_GRAY = colors.HexColor('#E0E0E0')
        DARK_GRAY = colors.HexColor('#999999')
        TERRA = colors.HexColor('#b56744')
        TERRA_LIGHT = colors.HexColor('#f7ede5')
        BORDER = colors.HexColor('#e0d9d0')
        
        s_head = ps('h', fontSize=9, fontName='Helvetica-Bold',
                   textColor=WHITE)
        s_body = ps('b', fontSize=8.5, fontName='Helvetica',
                   textColor=WHITE, leading=13)
        s_right = ps('r', fontSize=8.5, fontName='Helvetica',
                   alignment=TA_RIGHT, textColor=WHITE)
        s_center = ps('c', fontSize=8, fontName='Helvetica',
                   alignment=TA_CENTER, textColor=DARK_GRAY)

        story = []

        header_data = [[
            Paragraph('<font name="Helvetica-Bold" size="20" color="#FFFFFF">VESKA</font><br/>'
                      '<font name="Helvetica" size="8" color="#b56744">Fashion · Style · Elegance</font>',
                      styles['Normal']),
            Paragraph(
                f'<font name="Helvetica-Bold" size="14" color="#FFFFFF">INVOICE</font><br/>'
                f'<font name="Helvetica" size="8" color="#D0D0D0">#{order.uuid}</font><br/>'
                f'<font name="Helvetica" size="8" color="#D0D0D0">'
                f'{order.created_at.strftime("%d %B %Y")}</font>',
                ps('hr', alignment=TA_RIGHT)
            ),
        ]]
        
        ht = Table(header_data, colWidths=[usable_w*0.6, usable_w*0.4])
        ht.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('BACKGROUND', (0,0), (-1,-1), colors.black),  
        ]))
        story.append(ht)
        story.append(HRFlowable(width=usable_w, thickness=1.5, color=TERRA, spaceAfter=10))
        
        address_parts = []
        if hasattr(order, 'address_line1') and order.address_line1:
            address_parts.append(order.address_line1)
        if hasattr(order, 'address_line2') and order.address_line2:
            address_parts.append(order.address_line2)
        if hasattr(order, 'city') and order.city:
            address_parts.append(order.city)
        if hasattr(order, 'state') and order.state:
            address_parts.append(order.state)
        if hasattr(order, 'pincode') and order.pincode:
            address_parts.append(order.pincode)
        
        address_one_line = ', '.join(address_parts)

        bt_data = [
            [Paragraph('<b color="#FFFFFF">Bill To</b>', s_head), 
             Paragraph('<b color="#FFFFFF">Order Info</b>', s_head)],
            [Paragraph(f'{order.full_name}<br/>{order.phone}', s_body),
             Paragraph(f'Order: <b color="#FFFFFF">#{order.uuid}</b>', s_body)],
            [Paragraph(address_one_line, s_body),
             Paragraph(f'Date: {order.created_at.strftime("%d %b %Y, %I:%M %p")}', s_body)],
            [Paragraph('', s_body), 
             Paragraph(f'Status: <b color="#FFFFFF">{order.get_status_display()}</b>', s_body)],
            [Paragraph('', s_body), 
             Paragraph(f'Payment: {order.get_payment_method_display()}', s_body)],
        ]
        
        bt = Table(bt_data, colWidths=[usable_w*0.55, usable_w*0.45])
        bt.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('BACKGROUND', (0,0), (-1,-1), colors.black), 
            ('TEXTCOLOR', (0,0), (-1,-1), WHITE),
        ]))
        story.append(bt)
        story.append(Spacer(1, 10))

        col_w = [usable_w*0.42, usable_w*0.13, usable_w*0.15, usable_w*0.15, usable_w*0.15]
        
        rows = [[
            Paragraph('<b color="#FFFFFF">Product</b>', s_head),
            Paragraph('<b color="#FFFFFF">Size</b>', ps('ch', alignment=TA_CENTER, fontSize=9, 
                       fontName='Helvetica-Bold', textColor=WHITE)),
            Paragraph('<b color="#FFFFFF">Qty</b>', ps('ch2', alignment=TA_CENTER, fontSize=9, 
                       fontName='Helvetica-Bold', textColor=WHITE)),
            Paragraph('<b color="#FFFFFF">Unit Price</b>', ps('rh', alignment=TA_RIGHT, fontSize=9, 
                       fontName='Helvetica-Bold', textColor=WHITE)),
            Paragraph('<b color="#FFFFFF">Total</b>', ps('rh2', alignment=TA_RIGHT, fontSize=9, 
                       fontName='Helvetica-Bold', textColor=WHITE)),
        ]]

        for it in items:
            note = ' <font color="#ff6b6b">(cancelled)</font>' if it.cancel_status == 'cancelled' else ''
            
            size_value = getattr(it, 'size', None) or getattr(it, 'size_name', None) or '—'
            
            if hasattr(it, 'line_total') and it.line_total:
                line_total = it.line_total
            else:
                line_total = it.quantity * it.unit_price
            
            rows.append([
                Paragraph(f'{it.product_name}{note}', s_body),
                Paragraph(str(size_value), ps('cc', alignment=TA_CENTER, fontSize=8.5, 
                           fontName='Helvetica', textColor=WHITE)),
                Paragraph(str(it.quantity), ps('ccc', alignment=TA_CENTER, fontSize=8.5, 
                           fontName='Helvetica', textColor=WHITE)),
                Paragraph(f'₹{it.unit_price:.2f}', s_right),
                Paragraph(f'₹{line_total:.2f}', s_right),
            ])

        item_table = Table(rows, colWidths=col_w, repeatRows=1)
        item_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.black),
            ('TEXTCOLOR', (0,0), (-1,0), WHITE),
            ('GRID', (0,0), (-1,-1), 0.4, BORDER),
            ('BACKGROUND', (0,1), (-1,-1), colors.black),  # Black background for data rows
            ('TEXTCOLOR', (0,1), (-1,-1), WHITE),  # White text
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(item_table)
        story.append(Spacer(1, 8))

        def tot_row(label, value, bold=False):
            fn = 'Helvetica-Bold' if bold else 'Helvetica'
            fs = 9 if bold else 8.5
            text_color = TERRA if bold else WHITE
            return ['', '', '',
                    Paragraph(f'<font color="{text_color.hexval()}">{label}</font>', 
                             ps(f'l{label}', fontSize=fs, fontName=fn, alignment=TA_RIGHT, 
                                textColor=text_color)),
                    Paragraph(f'<font color="{text_color.hexval()}">{value}</font>', 
                             ps(f'v{label}', fontSize=fs, fontName=fn, alignment=TA_RIGHT, 
                                textColor=text_color))]

        tot_rows = [tot_row('Subtotal', f'₹{order.subtotal:.2f}')]
        if order.discount_amount:
            tot_rows.append(tot_row(f'Discount ({order.coupon_code})', f'−₹{order.discount_amount:.2f}'))
        tot_rows.append(tot_row('Shipping', 'FREE' if order.shipping_charge == 0 else f'₹{order.shipping_charge:.2f}'))
        tot_rows.append(tot_row('TOTAL', f'₹{order.total:.2f}', bold=True))

        tot_table = Table(tot_rows, colWidths=col_w)
        tot_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.black),
            ('TEXTCOLOR', (0,0), (-1,-1), WHITE),
            ('LINEABOVE', (3, len(tot_rows)-1), (-1, len(tot_rows)-1), 1, TERRA),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(tot_table)
        story.append(Spacer(1, 16))
        story.append(HRFlowable(width=usable_w, thickness=0.5, color=BORDER, spaceAfter=8))
        
        story.append(Paragraph(
            '<font color="#D0D0D0">Thank you for shopping with Veska! '
            'For queries contact support@veska.in · www.veska.in</font>', s_center))

        doc.build(story)
        buf.seek(0)
        response = HttpResponse(buf, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="Veska_Invoice_{order.uuid}.pdf"')
        return response

    except ImportError as e:
        print(f"ReportLab import error: {e}")
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