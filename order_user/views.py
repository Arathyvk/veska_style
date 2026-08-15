import io
import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Q, Avg
from django.http import HttpResponse
from datetime import timedelta
from decimal import Decimal
from django.db import transaction as db_tx
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle,Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from django.http import JsonResponse

from order_user.order_email import send_order_confirmation
from order_user.models import Order, OrderItem
from order_admin.models import ReturnRequest, RETURN_DAYS
from product_admin.models import  ProductReview
from wallet_user.utils import refund_on_cancellation, refund_single_item_cancellation
from coupon_admin.models import Coupon, CouponUsage


NON_RETURNABLE_CATEGORIES = [
    'hygiene', 'personalised', 'final_sale',
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
    ('wrong_item',     'Ordered wrong item/size'),
    ('found_cheaper',  'Found better price elsewhere'),
    ('delivery_delay', 'Delivery is taking too long'),
    ('payment_issue',  'Payment issue'),
    ('other',          'Other'),
]

RETURN_REASONS = [
    ('wrong_size',       'Wrong size received'),
    ('wrong_item',       'Wrong item received'),
    ('defective',        'Defective / damaged product'),
    ('not_as_described', 'Not as described'),
    ('changed_mind',     'Changed my mind'),
    ('quality_issue',    'Quality not as expected'),
    ('other',            'Other'),
]


def _recalculate_order_summary(order, active_items=None):
    if active_items is None:
        active_items = order.items.filter(cancel_status='none')

    subtotal = sum((item.line_total or Decimal('0.00')) for item in active_items)
    shipping = Decimal(order.shipping_charge or 0)
    coupon_discount = Decimal(order.discount_amount or 0)
    offer_discount = Decimal(order.offer_discount or 0)
    wallet_used = Decimal(order.wallet_amount_used or 0)
    original_subtotal = Decimal(str(order.subtotal or 0))

    prorated_coupon_discount = Decimal('0.00')
    prorated_offer_discount = Decimal('0.00')

    if original_subtotal > 0 and subtotal > 0:
        if coupon_discount > 0:
            prorated_coupon_discount = (
                subtotal * coupon_discount / original_subtotal
            ).quantize(Decimal('0.01'))
        if offer_discount > 0:
            prorated_offer_discount = (
                subtotal * offer_discount / original_subtotal
            ).quantize(Decimal('0.01'))

    final_total = max(
        subtotal - prorated_offer_discount - prorated_coupon_discount + shipping - wallet_used,
        Decimal('0.00'),
    )

    return (
        subtotal,
        prorated_offer_discount,
        prorated_coupon_discount,
        shipping,
        wallet_used,
        final_total,
    )


@login_required
def order_list(request):
    qs = Order.objects.filter(user=request.user).prefetch_related('items', 'return_requests')

    search_query = request.GET.get('q', '').strip()
    if search_query:
        qs = qs.filter(
            Q(items__product_name__icontains=search_query) |
            Q(status__icontains=search_query)              |
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
    all_items = order.items.all()
    active_items = order.items.filter(cancel_status='none')

    subtotal, offer_discount, coupon_discount, shipping, wallet_used, final_total = _recalculate_order_summary(order, active_items)
    offer_details = order.offer_details or ''
    coupon_code = order.coupon_code or ''

    product_ids = all_items.values_list('product_id', flat=True)

    reviews_qs = ProductReview.objects.filter(
        product_id__in=product_ids,
        user=request.user,
        is_approved=True
    ).order_by('-created_at')

    review_count = reviews_qs.count()
    avg_rating = 0
    rating_breakdown = [0, 0, 0, 0, 0]

    if review_count:
        avg_rating = round(reviews_qs.aggregate(avg=Avg('rating'))['avg'] or 0, 1)
        for r in reviews_qs:
            if 1 <= r.rating <= 5:
                rating_breakdown[5 - r.rating] += 1

    reviews = list(reviews_qs[:10])

    can_review = order.status in ['delivered', 'confirmed', 'returned']

    reviewed_product_ids = ProductReview.objects.filter(
        user=request.user,
        product_id__in=product_ids
    ).values_list('product_id', flat=True)

    return render(request, 'order_detail.html', {
        'order':            order,
        'items':            all_items,
        'active_items':     active_items,
        'steps':            TIMELINE_STEPS,
        'subtotal':         subtotal,
        'shipping':         shipping,
        'coupon_discount':  coupon_discount,
        'coupon_code':      coupon_code,
        'offer_discount':   offer_discount,
        'offer_details':    offer_details,
        'wallet_used':      wallet_used,
        'final_total':      final_total,
        'reviews':          reviews,
        'avg_rating':       avg_rating,
        'review_count':     review_count,
        'rating_breakdown': rating_breakdown,
        'can_review':       can_review,
        'reviewed_product_ids': reviewed_product_ids,
    })


@login_required(login_url='login')
@require_POST
def submit_review(request):

    product_id = request.POST.get("product_id")
    rating = request.POST.get("rating")
    comment = request.POST.get("comment", "").strip()
    order_id = request.POST.get("order_id")

    if not product_id or not rating:
        return JsonResponse(
            {"success": False, "error": "Product and rating are required"},
            status=400
        )

    try:
        rating = int(rating)
    except ValueError:
        return JsonResponse(
            {"success": False, "error": "Invalid rating"},
            status=400
        )

    order_item = OrderItem.objects.filter(
        order_id=order_id,
        product_id=product_id,
        order__user=request.user,
        order__status__in=["delivered", "confirmed", "returned"]
    ).first()

    if not order_item:
        return JsonResponse(
            {"success": False, "error": "You cannot review this product"},
            status=403
        )

    if ProductReview.objects.filter(
        user=request.user,
        product_id=product_id
    ).exists():
        return JsonResponse(
            {"success": False, "error": "You already reviewed this product"},
            status=400
        )

    author = f"{request.user.first_name} {request.user.last_name or ''}".strip()

    if not author:
        author = request.user.email

    review = ProductReview.objects.create(
        user=request.user,
        product_id=product_id,
        author_name=author,
        rating=rating,
        body=comment,
        is_approved=False,
    )

    return JsonResponse({
        "success": True,
        "message": "Review submitted successfully.",
        "review_id": review.id,
    })


@login_required
def order_success(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)
    items = order.items.all()

    subtotal = Decimal('0')
    for item in items:
        subtotal += item.unit_price * item.quantity

    shipping        = Decimal(order.shipping_charge or 0)
    coupon_discount = Decimal(order.discount_amount or 0)
    coupon_code     = order.coupon_code or ''
    offer_discount  = Decimal(order.offer_discount or 0)
    offer_details   = order.offer_details or ''
    wallet_used     = Decimal(order.wallet_amount_used or 0)

    final_total = max(
        subtotal - offer_discount - coupon_discount + shipping - wallet_used,
        Decimal('0'),
    )

    session_key = f"order_confirmed_{uuid}"
    if not request.session.get(session_key):
        send_order_confirmation(order)
        request.session[session_key] = True

    return render(request, 'order_success.html', {
        'order':           order,
        'order_items':     items,
        'subtotal':        subtotal,
        'shipping':        shipping,
        'coupon_discount': coupon_discount,
        'coupon_code':     coupon_code,
        'offer_discount':  offer_discount,
        'offer_details':   offer_details,
        'wallet_used':     wallet_used,
        'final_total':     final_total,
    })



@login_required
def cancel_order(request, uuid):

    order = get_object_or_404(Order, uuid=uuid, user=request.user)

    if not order.can_cancel:
        messages.error(request, "Cannot cancel")
        return redirect("order_detail", uuid=order.uuid)

    if request.method == "POST":
        refund = refund_on_cancellation(order)

        if order.coupon_code:
            try:
                coupon_obj = Coupon.objects.get(code=order.coupon_code)
                coupon_obj.times_used = max(0, coupon_obj.times_used - 1)
                coupon_obj.save(update_fields=['times_used'])
                CouponUsage.objects.filter(user=order.user, coupon=coupon_obj, order=order).delete()
            except Coupon.DoesNotExist:
                pass

        order.status = "cancelled"
        order.cancelled_at = timezone.now()
        order.save(update_fields=["status", "cancelled_at"])

        return redirect("order_list")
    return render(request, "cancel_order.html", {"order": order})


@require_POST
@login_required(login_url='login')
def cancel_order_item(request, uuid, item_id):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)
    item = get_object_or_404(OrderItem, id=item_id, order=order)

    if item.cancel_status != 'none':
        message = "This item has already been cancelled."
        if request.content_type and 'application/json' in request.content_type:
            return JsonResponse({"success": False, "error": message}, status=400)
        messages.error(request, message)
        return redirect("order_detail", uuid=order.uuid)

    if not item.can_cancel:
        message = "This item can no longer be cancelled."
        if request.content_type and 'application/json' in request.content_type:
            return JsonResponse({"success": False, "error": message}, status=400)
        messages.error(request, message)
        return redirect("order_detail", uuid=order.uuid)

    if request.content_type and 'application/json' in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        reason = str(payload.get("reason") or payload.get("cancel_reason") or "").strip()
    else:
        reason = request.POST.get("cancel_reason", request.POST.get("reason", "")).strip()

    if not reason:
        reason = "No reason provided"

    with db_tx.atomic():
        item.cancel_status = "cancelled"
        item.is_cancelled = True
        item.cancel_reason = reason
        item.save(update_fields=["cancel_status", "is_cancelled", "cancel_reason"])

        if item.variant:
            item.variant.stock += item.quantity
            item.variant.save(update_fields=["stock"])

    refund_amount = refund_single_item_cancellation(order, item)

    active_items = order.items.filter(cancel_status="none")
    subtotal, prorated_offer_discount, prorated_coupon_discount, shipping, wallet_used, final_total = _recalculate_order_summary(order, active_items)

    if not active_items.exists():
        order.status = "cancelled"
        order.cancelled_at = timezone.now()
        order.total = Decimal('0.00')
        order.save(update_fields=["status", "cancelled_at", "total"])

        if order.coupon_code:
            try:
                coupon_obj = Coupon.objects.get(code=order.coupon_code)
                coupon_obj.times_used = max(0, coupon_obj.times_used - 1)
                coupon_obj.save(update_fields=['times_used'])
                CouponUsage.objects.filter(user=order.user, coupon=coupon_obj, order=order).delete()
            except Coupon.DoesNotExist:
                pass
    else:
        order.total = final_total
        order.save(update_fields=["total"])

    if request.content_type and 'application/json' in request.content_type:
        return JsonResponse({
            "success": True,
            "message": (
                f"Item cancelled successfully. ₹{refund_amount} refunded to your wallet."
                if refund_amount > 0 else "Item cancelled successfully."
            ),
            "new_total": str(final_total.quantize(Decimal("0.01"))),
            "new_subtotal": str(subtotal.quantize(Decimal("0.01"))),
            "new_discount": str((prorated_offer_discount + prorated_coupon_discount).quantize(Decimal("0.01"))),
            "order_cancelled": order.status == "cancelled",
        })

    if refund_amount > 0:
        messages.success(
            request,
            f"Item cancelled successfully. ₹{refund_amount} refunded to your wallet."
        )
    else:
        messages.success(request, "Item cancelled successfully.")

    return redirect("order_detail", uuid=order.uuid)


@login_required
def return_order(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)

    if not order.can_return:
        messages.error(request, "This order is not eligible for return.")
        return redirect('order_detail', uuid=order.uuid)

    returnable_items = []
    for item in order.items.all():
        item.return_request = ReturnRequest.objects.filter(
            order_item=item, user=request.user
        ).first()
        returnable_items.append(item)

    return_deadline = order.delivered_at + timedelta(days=RETURN_DAYS)
    days_left = max(0, (return_deadline - timezone.now()).days)

    return render(request, 'return_order.html', {
        'order':           order,
        'returnable_items': returnable_items,
        'return_deadline': return_deadline,
        'days_left':       days_left,
    })


@login_required
def return_request(request, uuid, item_id):
    order      = get_object_or_404(Order, uuid=uuid, user=request.user)
    order_item = get_object_or_404(OrderItem, pk=item_id, order=order)

    if order.status != 'delivered':
        messages.error(request, 'Returns can only be requested for delivered orders.')
        return redirect('order_detail', uuid=order.uuid)

    if not order.delivered_at:
        messages.error(request, 'Delivery date not recorded. Please contact support.')
        return redirect('order_detail', uuid=order.uuid)

    existing_return = ReturnRequest.objects.filter(
        order_item=order_item, user=request.user
    ).first()

    category_slug = ''
    if order_item.product and order_item.product.category:
        category_slug = order_item.product.category.slug.lower()
    is_returnable_category = category_slug not in NON_RETURNABLE_CATEGORIES

    return_deadline  = order.delivered_at + timedelta(days=RETURN_DAYS)
    deadline_expired = timezone.now() > return_deadline
    days_left        = max(0, (return_deadline - timezone.now()).days)

    if request.method == 'POST':

        if existing_return:
            messages.error(request, 'A return has already been requested for this item.')
            return redirect('return_request', uuid=order.uuid, item_id=item_id)

        if not is_returnable_category:
            messages.error(request, 'This item is not eligible for return.')
            return redirect('order_detail', uuid=order.uuid)

        if deadline_expired:
            messages.error(request, 'The return window for this order has closed.')
            return redirect('order_detail', uuid=order.uuid)

        return_reason = request.POST.get('return_reason', '').strip()
        return_notes  = request.POST.get('return_notes', '').strip()
        confirmed     = request.POST.get('confirm_conditions') == 'on'

        if not return_reason:
            messages.error(request, 'Please select a return reason.')
            return render(request, 'return_request.html', {
                'order': order, 'order_item': order_item,
                'existing_return': existing_return,
                'is_returnable_category': is_returnable_category,
                'deadline_expired': deadline_expired,
                'return_deadline': return_deadline,
                'days_left': days_left, 'reasons': RETURN_REASONS,
            })

        if not confirmed:
            messages.error(request, 'Please confirm the return conditions.')
            return render(request, 'return_request.html', {
                'order': order, 'order_item': order_item,
                'existing_return': existing_return,
                'is_returnable_category': is_returnable_category,
                'deadline_expired': deadline_expired,
                'return_deadline': return_deadline,
                'days_left': days_left, 'reasons': RETURN_REASONS,
            })

        with db_tx.atomic():
            ReturnRequest.objects.create(
                user=request.user,
                order=order,
                order_item=order_item,
                return_reason=return_reason,
                return_notes=return_notes,
                status='pending',
            )

            order.status              = 'return_requested'
            order.return_requested_at = timezone.now()
            order.return_reason       = return_reason
            order.save(update_fields=['status', 'return_requested_at', 'return_reason'])

        messages.success(
            request,
            'Return request submitted successfully. '
            'We will process it and refund to your wallet once approved.'
        )
        return redirect('order_detail', uuid=order.uuid)

    return render(request, 'return_request.html', {
        'order':                 order,
        'order_item':            order_item,
        'existing_return':       existing_return,
        'is_returnable_category': is_returnable_category,
        'deadline_expired':      deadline_expired,
        'return_deadline':       return_deadline,
        'days_left':             days_left,
        'reasons':               RETURN_REASONS,
    })


@login_required
def return_order_redirect(request, short_id):
    order = Order.objects.filter(
        uuid__startswith=short_id.upper(), user=request.user
    ).first()
    if order:
        return redirect('return_order', uuid=order.uuid)
    messages.error(request, "Order not found.")
    return redirect('order_list')



@login_required
def download_invoice(request, uuid):
    order = get_object_or_404(Order, uuid=uuid, user=request.user)
    all_items = order.items.all()
    active_items = order.items.filter(cancel_status='none')

    subtotal, offer_discount, coupon_discount, shipping, wallet_used, final_total = _recalculate_order_summary(order, active_items)
    items = all_items

    try:


        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=20*mm, rightMargin=20*mm,
            topMargin=18*mm, bottomMargin=18*mm,
            title=f"Invoice_{order.uuid}",
        )

        styles   = getSampleStyleSheet()
        W, _     = A4
        usable_w = W - 40*mm

        def ps(name, **kw):
            return ParagraphStyle(name, **kw)

        WHITE     = colors.HexColor('#FFFFFF')
        DARK_GRAY = colors.HexColor('#999999')
        TERRA     = colors.HexColor('#b56744')
        BORDER    = colors.HexColor('#e0d9d0')

        s_head  = ps('h',  fontSize=9,   fontName='Helvetica-Bold', textColor=WHITE)
        s_body  = ps('b',  fontSize=8.5, fontName='Helvetica',      textColor=WHITE, leading=13)
        s_right = ps('r',  fontSize=8.5, fontName='Helvetica',      textColor=WHITE, alignment=TA_RIGHT)
        s_center= ps('c',  fontSize=8,   fontName='Helvetica',      textColor=DARK_GRAY, alignment=TA_CENTER)

        story = []

        header_data = [[
            Paragraph(
                '<font name="Helvetica-Bold" size="20" color="#FFFFFF">VESKA</font><br/>'
                '<font name="Helvetica" size="8" color="#b56744">Fashion · Style · Elegance</font>',
                styles['Normal'],
            ),
            Paragraph(
                f'<font name="Helvetica-Bold" size="14" color="#FFFFFF">INVOICE</font><br/>'
                f'<font name="Helvetica" size="8" color="#D0D0D0">#{order.uuid}</font><br/>'
                f'<font name="Helvetica" size="8" color="#D0D0D0">{order.created_at.strftime("%d %B %Y")}</font>',
                ps('hr', alignment=TA_RIGHT),
            ),
        ]]
        ht = Table(header_data, colWidths=[usable_w*0.6, usable_w*0.4])
        ht.setStyle(TableStyle([
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('BACKGROUND',    (0,0), (-1,-1), colors.black),
        ]))
        story.append(ht)
        story.append(HRFlowable(width=usable_w, thickness=1.5, color=TERRA, spaceAfter=10))

        address_parts = [
            p for p in [
                order.address_line1, order.address_line2,
                order.city, order.state, order.pincode,
            ] if p
        ]
        address_line = ', '.join(address_parts)

        bt_data = [
            [Paragraph('<b>Bill To</b>',    s_head), Paragraph('<b>Order Info</b>', s_head)],
            [Paragraph(f'{order.full_name}<br/>{order.phone}', s_body),
             Paragraph(f'Order: <b>#{order.uuid}</b>', s_body)],
            [Paragraph(address_line, s_body),
             Paragraph(f'Date: {order.created_at.strftime("%d %b %Y, %I:%M %p")}', s_body)],
            [Paragraph('', s_body), Paragraph(f'Status: <b>{order.get_status_display()}</b>', s_body)],
            [Paragraph('', s_body), Paragraph(f'Payment: {order.get_payment_method_display()}', s_body)],
        ]
        bt = Table(bt_data, colWidths=[usable_w*0.55, usable_w*0.45])
        bt.setStyle(TableStyle([
            ('VALIGN',        (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('BACKGROUND',    (0,0), (-1,-1), colors.black),
            ('TEXTCOLOR',     (0,0), (-1,-1), WHITE),
        ]))
        story.append(bt)
        story.append(Spacer(1, 10))

        col_w = [usable_w*0.42, usable_w*0.13, usable_w*0.15, usable_w*0.15, usable_w*0.15]
        rows = [[
            Paragraph('<b>Product</b>',    s_head),
            Paragraph('<b>Size</b>',       ps('ch',  alignment=TA_CENTER, fontSize=9, fontName='Helvetica-Bold', textColor=WHITE)),
            Paragraph('<b>Qty</b>',        ps('ch2', alignment=TA_CENTER, fontSize=9, fontName='Helvetica-Bold', textColor=WHITE)),
            Paragraph('<b>Unit Price</b>', ps('rh',  alignment=TA_RIGHT,  fontSize=9, fontName='Helvetica-Bold', textColor=WHITE)),
            Paragraph('<b>Total</b>',      ps('rh2', alignment=TA_RIGHT,  fontSize=9, fontName='Helvetica-Bold', textColor=WHITE)),
        ]]

        for it in items:
            note       = ' <font color="#ff6b6b">(cancelled)</font>' if it.cancel_status == 'cancelled' else ''
            size_value = it.size or '—'
            line_total = it.line_total or (it.unit_price * it.quantity)

            rows.append([
                Paragraph(f'{it.product_name}{note}', s_body),
                Paragraph(str(size_value), ps('cc',  alignment=TA_CENTER, fontSize=8.5, fontName='Helvetica', textColor=WHITE)),
                Paragraph(str(it.quantity), ps('ccc', alignment=TA_CENTER, fontSize=8.5, fontName='Helvetica', textColor=WHITE)),
                Paragraph(f'₹{it.unit_price:.2f}', s_right),
                Paragraph(f'₹{line_total:.2f}',    s_right),
            ])

        item_table = Table(rows, colWidths=col_w, repeatRows=1)
        item_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0),  colors.black),
            ('BACKGROUND',    (0,1), (-1,-1), colors.black),
            ('TEXTCOLOR',     (0,0), (-1,-1), WHITE),
            ('GRID',          (0,0), (-1,-1), 0.4, BORDER),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 6),
            ('RIGHTPADDING',  (0,0), (-1,-1), 6),
        ]))
        story.append(item_table)
        story.append(Spacer(1, 8))

        def tot_row(label, value, bold=False, color=None):
            fn = 'Helvetica-Bold' if bold else 'Helvetica'
            fs = 9 if bold else 8.5
            if color:
                tc = color
            else:
                tc = TERRA if bold else WHITE
            return [
                '', '', '',
                Paragraph(label, ps(
                    f'l_{label[:8]}',
                    fontSize=fs, fontName=fn,
                    alignment=TA_RIGHT, textColor=tc,
                )),
                Paragraph(value, ps(
                    f'v_{label[:8]}',
                    fontSize=fs, fontName=fn,
                    alignment=TA_RIGHT, textColor=tc,
                )),
            ]

        _subtotal     = subtotal
        _offer_disc   = offer_discount
        _coupon_disc  = coupon_discount
        _shipping     = shipping
        _wallet_used  = wallet_used
        
        total_paid_by_customer = _subtotal - _offer_disc - _coupon_disc + _shipping
        if total_paid_by_customer < 0:
            total_paid_by_customer = Decimal('0')
        
        is_cod = order.payment_method == 'cod'
        
        is_cancelled_or_returned = order.status in ['cancelled', 'returned']
        
        if is_cancelled_or_returned:
            if is_cod:
                paid_amount = Decimal('0')
                show_refund = False
            else:
                paid_amount = Decimal('0')
                show_refund = True
                refund_amount = total_paid_by_customer
        else:
            paid_amount = total_paid_by_customer
            show_refund = False

        tot_rows = [tot_row('Subtotal', f'Rs.{_subtotal:.2f}')]

        if _offer_disc:
            tot_rows.append(tot_row(
                'Offer Discount',
                f'-Rs.{_offer_disc:.2f}',
            ))

        if _coupon_disc:
            coupon_label = (
                f'Coupon ({order.coupon_code})'
                if order.coupon_code else 'Coupon Discount'
            )
            tot_rows.append(tot_row(coupon_label, f'-Rs.{_coupon_disc:.2f}'))

        tot_rows.append(tot_row(
            'Shipping',
            'FREE' if not _shipping else f'Rs.{_shipping:.2f}',
        ))

        if _wallet_used:
            tot_rows.append(tot_row(
                'Paid via Wallet',
                f'Rs.{_wallet_used:.2f}',
            ))

        if is_cancelled_or_returned:
            if is_cod:
                tot_rows.append(tot_row(
                    'Amount Payable (COD)',
                    'Rs.0.00',
                ))
                tot_rows.append(tot_row(
                    'STATUS',
                    'CANCELLED/RETURNED',
                    bold=True,
                    color=colors.HexColor('#ff6b6b'),
                ))
            else:
                original_payment = total_paid_by_customer - _wallet_used
                if original_payment > 0:
                    tot_rows.append(tot_row(
                        f'Paid via {order.get_payment_method_display()}',
                        f'Rs.{original_payment:.2f}',
                    ))
                
                if show_refund:
                    tot_rows.append(tot_row(
                        'REFUNDED',
                        f'-Rs.{total_paid_by_customer:.2f}',
                        color=colors.HexColor('#3a7d5a'),
                    ))
                    
                tot_rows.append(tot_row(
                    'TOTAL PAID',
                    'Rs.0.00',
                    bold=True,
                ))
                
                if _wallet_used > 0:
                    tot_rows.append(tot_row(
                        'Wallet Refund',
                        f'Rs.{_wallet_used:.2f}',
                        color=colors.HexColor('#3a7d5a'),
                    ))
        else:
            if not is_cod:
                stripe_amount = total_paid_by_customer - _wallet_used
                if stripe_amount > 0:
                    tot_rows.append(tot_row(
                        f'Paid via {order.get_payment_method_display()}',
                        f'Rs.{stripe_amount:.2f}',
                    ))
            
            tot_rows.append(tot_row(
                'TOTAL PAID' if not is_cod else 'TOTAL AMOUNT',
                f'Rs.{total_paid_by_customer:.2f}',
                bold=True,
            ))
            
            if is_cod:
                tot_rows.append(tot_row(
                    '(Payable on Delivery)',
                    '',
                    color=colors.HexColor('#D0D0D0'),
                ))

        tot_table = Table(tot_rows, colWidths=col_w)
        tot_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), colors.black),
            ('TEXTCOLOR',     (0, 0), (-1, -1), WHITE),
            ('LINEABOVE',     (3, len(tot_rows)-1), (-1, len(tot_rows)-1), 1, TERRA),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(tot_table)
        story.append(Spacer(1, 16))
        story.append(HRFlowable(width=usable_w, thickness=0.5, color=BORDER, spaceAfter=8))
        story.append(Paragraph(
            '<font color="#D0D0D0">Thank you for shopping with Veska! '
            'For queries contact support@veska.in · www.veska.in</font>',
            s_center,
        ))

        doc.build(story)
        buf.seek(0)
        response = HttpResponse(buf, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="Veska_Invoice_{order.uuid}.pdf"'
        )
        return response

    except ImportError as e:
        return _html_invoice_fallback(request, order, items)


def _html_invoice_fallback(request, order, items):
    return render(request, 'invoice_html.html', {'order': order, 'items': items})



def _restore_stock(item: OrderItem):
    
    if item.variant:
        item.variant.stock += item.quantity
        item.variant.save(update_fields=["stock"])