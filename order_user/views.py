from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Q
from django.http import HttpResponse

from order_user.models import Order, OrderItem
from product_admin.models import ProductVariant




@login_required
def order_list(request):
    qs = Order.objects.filter(user=request.user).prefetch_related('items')

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
        'orders':        orders,
        'search_query':  search_query,
        'status_filter': status_filter,
        'status_choices': Order.STATUS_CHOICES,
        'total_orders':  orders.count()
    })




@login_required
def order_detail(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    items = order.items.all()

    active_items    = items.filter(status='active')
    cancelled_items = items.filter(status='cancelled')

    return render(request, 'order_detail.html', {
        'order':           order,
        'items':           items,
        'active_items':    active_items,
        'cancelled_items': cancelled_items,
    })




@login_required
def order_success(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    return render(request, 'order_success.html', {'order': order})



@login_required
def cancel_order(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)

    if not order.can_cancel:
        messages.error(
            request,
            f'Order #{order.order_number} cannot be cancelled '
            f'(current status: {order.get_status_display()}).'
        )
        return redirect('order_detail', order_number=order_number)

    if request.method == 'POST':
        reason = request.POST.get('cancel_reason', '').strip()

        for item in order.items.filter(status='active'):
            _restore_stock(item)
            item.status       = 'cancelled'
            item.cancel_reason = reason
            item.cancelled_at  = timezone.now()
            item.save(update_fields=['status', 'cancel_reason', 'cancelled_at'])

        order.status        = 'cancelled'
        order.cancel_reason = reason
        order.cancelled_at  = timezone.now()
        order.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])

        messages.success(
            request,
            f'Order #{order.order_number} has been cancelled successfully.'
        )
        return redirect('order_detail', order_number=order_number)

    return render(request, 'cancel_order.html', {'order': order})




@login_required
def cancel_order_item(request, order_number, item_id):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    item  = get_object_or_404(OrderItem, id=item_id, order=order)

    if not item.can_cancel:
        messages.error(request, f'"{item.product_name}" cannot be cancelled at this stage.')
        return redirect('order_detail', order_number=order_number)

    if request.method == 'POST':
        reason = request.POST.get('cancel_reason', '').strip()

        _restore_stock(item)
        item.status        = 'cancelled'
        item.cancel_reason = reason
        item.cancelled_at  = timezone.now()
        item.save(update_fields=['status', 'cancel_reason', 'cancelled_at'])

        if not order.items.filter(status='active').exists():
            order.status       = 'cancelled'
            order.cancel_reason = 'All items cancelled by user'
            order.cancelled_at  = timezone.now()
            order.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])
            messages.success(
                request,
                f'"{item.product_name}" was the last item — order #{order.order_number} has been fully cancelled.'
            )
        else:
            messages.success(request, f'"{item.product_name}" has been cancelled.')

        return redirect('order_detail', order_number=order_number)

    return render(request, 'cancel_item.html', {
        'order': order,
        'item':  item,
    })



@login_required
def return_order(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)

    if not order.can_return:
        messages.error(
            request,
            f'Return is only available for delivered orders '
            f'(current status: {order.get_status_display()}).'
        )
        return redirect('order_detail', order_number=order_number)

    if request.method == 'POST':
        reason = request.POST.get('return_reason', '').strip()
        if not reason:
            messages.error(request, 'A reason is required to request a return.')
            return render(request, 'return_order.html', {
                'order': order,
                'error': 'Please provide a reason for the return.',
            })

        order.status               = 'return_requested'
        order.return_reason        = reason
        order.return_requested_at  = timezone.now()
        order.save(update_fields=[
            'status', 'return_reason', 'return_requested_at', 'updated_at'
        ])

        messages.success(
            request,
            f'Return request for order #{order.order_number} submitted. '
            f'Our team will reach out within 2–3 business days.'
        )
        return redirect('order_detail', order_number=order_number)

    return render(request, 'return_order.html', {'order': order})




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
        from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
        import io

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=20*mm, rightMargin=20*mm,
            topMargin=18*mm, bottomMargin=18*mm,
        )

        styles   = getSampleStyleSheet()
        W, H     = A4
        usable_w = W - 40*mm

        def style(name, **kw):
            s = ParagraphStyle(name, **kw)
            return s

        s_title   = style('t', fontSize=22, fontName='Helvetica-Bold', spaceAfter=2)
        s_sub     = style('s', fontSize=9,  fontName='Helvetica', textColor=colors.HexColor('#7a6f66'))
        s_head    = style('h', fontSize=9,  fontName='Helvetica-Bold', textColor=colors.HexColor('#2e2925'))
        s_body    = style('b', fontSize=8.5, fontName='Helvetica', textColor=colors.HexColor('#2e2925'), leading=13)
        s_right   = style('r', fontSize=8.5, fontName='Helvetica', alignment=TA_RIGHT, textColor=colors.HexColor('#2e2925'))
        s_bold_r  = style('br', fontSize=9, fontName='Helvetica-Bold', alignment=TA_RIGHT)
        s_total   = style('tot', fontSize=11, fontName='Helvetica-Bold', alignment=TA_RIGHT, textColor=colors.HexColor('#2e2925'))
        s_center  = style('c', fontSize=8, fontName='Helvetica', alignment=TA_CENTER, textColor=colors.HexColor('#b0a699'))

        TERRA  = colors.HexColor('#b56744')
        LIGHT  = colors.HexColor('#f2ede6')
        BORDER = colors.HexColor('#e0d9d0')
        INK    = colors.HexColor('#2e2925')

        story = []

        header_data = [[
            Paragraph('<font name="Helvetica-Bold" size="20" color="#2e2925">VESKA</font><br/>'
                      '<font name="Helvetica" size="8" color="#b56744">Fashion · Style · Elegance</font>', styles['Normal']),
            Paragraph(
                f'<font name="Helvetica-Bold" size="14" color="#2e2925">INVOICE</font><br/>'
                f'<font name="Helvetica" size="8" color="#7a6f66">#{order.order_number}</font><br/>'
                f'<font name="Helvetica" size="8" color="#7a6f66">'
                f'{order.created_at.strftime("%d %B %Y")}</font>',
                ParagraphStyle('hr', alignment=TA_RIGHT)
            ),
        ]]
        ht = Table(header_data, colWidths=[usable_w*0.6, usable_w*0.4])
        ht.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(ht)
        story.append(HRFlowable(width=usable_w, thickness=1.5, color=TERRA, spaceAfter=10))

        bill_info = [
            [Paragraph('<b>Bill To</b>', s_head),
             Paragraph('<b>Order Info</b>', s_head)],
            [Paragraph(f'{order.full_name}<br/>{order.phone}', s_body),
             Paragraph(f'Order: <b>#{order.order_number}</b>', s_body)],
            [Paragraph(order.address_one_line, s_body),
             Paragraph(f'Date: {order.created_at.strftime("%d %b %Y, %I:%M %p")}', s_body)],
            [Paragraph('', s_body),
             Paragraph(f'Status: <b>{order.get_status_display()}</b>', s_body)],
            [Paragraph('', s_body),
             Paragraph(f'Payment: {order.get_payment_method_display()}', s_body)],
        ]
        bt = Table(bill_info, colWidths=[usable_w*0.55, usable_w*0.45])
        bt.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('BACKGROUND', (0,0), (-1,0), LIGHT),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.white]),
        ]))
        story.append(bt)
        story.append(Spacer(1, 10))

        col_w = [usable_w*0.42, usable_w*0.13, usable_w*0.15, usable_w*0.15, usable_w*0.15]
        item_header = [
            Paragraph('<b>Product</b>', s_head),
            Paragraph('<b>Size</b>',    ParagraphStyle('c', alignment=TA_CENTER, fontSize=9, fontName='Helvetica-Bold')),
            Paragraph('<b>Qty</b>',     ParagraphStyle('c', alignment=TA_CENTER, fontSize=9, fontName='Helvetica-Bold')),
            Paragraph('<b>Unit Price</b>', ParagraphStyle('r2', alignment=TA_RIGHT, fontSize=9, fontName='Helvetica-Bold')),
            Paragraph('<b>Total</b>',   ParagraphStyle('r3', alignment=TA_RIGHT, fontSize=9, fontName='Helvetica-Bold')),
        ]

        rows = [item_header]
        for it in items:
            status_note = ' <font color="#b53333">(cancelled)</font>' if it.status == 'cancelled' else ''
            rows.append([
                Paragraph(f'{it.product_name}{status_note}', s_body),
                Paragraph(it.size or '—', ParagraphStyle('cc', alignment=TA_CENTER, fontSize=8.5, fontName='Helvetica')),
                Paragraph(str(it.quantity), ParagraphStyle('ccc', alignment=TA_CENTER, fontSize=8.5, fontName='Helvetica')),
                Paragraph(f'₹{it.unit_price:.2f}', s_right),
                Paragraph(f'₹{it.line_total:.2f}', s_right),
            ])

        item_table = Table(rows, colWidths=col_w, repeatRows=1)
        item_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1,  0), INK),
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.white),
            ('GRID',          (0, 0), (-1, -1), 0.4, BORDER),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, LIGHT]),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ]))
        story.append(item_table)
        story.append(Spacer(1, 8))

        def tot_row(label, value, bold=False):
            lp = ParagraphStyle('l', fontSize=9 if bold else 8.5,
                                fontName='Helvetica-Bold' if bold else 'Helvetica',
                                alignment=TA_RIGHT, textColor=INK)
            vp = ParagraphStyle('v', fontSize=9 if bold else 8.5,
                                fontName='Helvetica-Bold' if bold else 'Helvetica',
                                alignment=TA_RIGHT, textColor=INK)
            return [Paragraph('', styles['Normal']),
                    Paragraph('', styles['Normal']),
                    Paragraph('', styles['Normal']),
                    Paragraph(label, lp),
                    Paragraph(value, vp)]

        tot_rows = []
        tot_rows.append(tot_row('Subtotal', f'₹{order.subtotal:.2f}'))
        if order.discount_amount:
            tot_rows.append(tot_row(f'Discount ({order.coupon_code})', f'−₹{order.discount_amount:.2f}'))
        tot_rows.append(tot_row('Shipping', f'FREE' if order.shipping_charge == 0 else f'₹{order.shipping_charge:.2f}'))
        tot_rows.append(tot_row('TOTAL', f'₹{order.total:.2f}', bold=True))

        tot_table = Table(tot_rows, colWidths=col_w)
        tot_table.setStyle(TableStyle([
            ('LINEABOVE', (3, len(tot_rows)-1), (-1, len(tot_rows)-1), 1, TERRA),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(tot_table)

        story.append(Spacer(1, 16))
        story.append(HRFlowable(width=usable_w, thickness=0.5, color=BORDER, spaceAfter=8))
        story.append(Paragraph(
            'Thank you for shopping with Veska! '
            'For queries contact support@veska.in · www.veska.in',
            s_center
        ))

        doc.build(story)
        buf.seek(0)

        response = HttpResponse(buf, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="Veska_Invoice_{order.order_number}.pdf"'
        )
        return response

    except ImportError:
        return _html_invoice_fallback(request, order, items)


def _html_invoice_fallback(request, order, items):
    return render(request, 'invoice_html.html', {
        'order': order,
        'items': items,
    })




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