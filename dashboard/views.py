import io
import json
import datetime

from django.db import models
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from django.db.models import Sum
from django.utils import timezone
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle,Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from django.http import HttpResponse


from order_user.models import Order, OrderItem
from product_admin.models import ProductVariant
from django.contrib.auth import get_user_model
from order_admin.models import ReturnRequest

User = get_user_model()

LOW_STOCK_THRESHOLD = 5
EXCLUDED_STATUSES = ["cancelled"]


def is_admin(user):
    return user.is_authenticated and user.is_staff


def _pct_change(current, previous):
    if not previous:
        return "+100%" if current else "0%"
    change = ((current - previous) / previous) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


def get_return_value_stats():
    approved_returns = ReturnRequest.objects.filter(
        status__in=['approved', 'completed']
    ).select_related('order', 'order_item')
    
    total_return_value = 0
    
    for ret in approved_returns:
        if ret.order_item:
            total_return_value += float(ret.order.total or 0)
    
    return {
        'total_value': total_return_value,
        'total_items': approved_returns.count(),
        'count': approved_returns.count(),
    }


def _get_net_revenue(queryset):
    paid_revenue = (
        queryset.filter(
            models.Q(payment_status__in=["paid", "completed", "success"]) |
            models.Q(payment_method="cod", status="delivered")
        )
        .exclude(status__in=EXCLUDED_STATUSES)
        .aggregate(s=Sum("total"))["s"]
        or 0
    )
    
    returned_revenue = (
        queryset.filter(
            status="returned", 
            payment_status="paid"
        )
        .aggregate(s=Sum("total"))["s"]
        or 0
    )
    
    cancelled_paid = (
        queryset.filter(
            status="cancelled",
            payment_status__in=["paid", "completed", "success"]
        )
        .aggregate(s=Sum("total"))["s"]
        or 0
    )
    
    net_revenue = float(paid_revenue) - float(returned_revenue) - float(cancelled_paid)
    
    return max(net_revenue, 0)


def _monthly_revenue(year):
    data = []
    for month in range(1, 13):
        month_orders = Order.objects.filter(
            created_at__year=year,
            created_at__month=month,
        )
        net_revenue = _get_net_revenue(month_orders)
        data.append(float(net_revenue))
    return data


@never_cache
@login_required(login_url="admin_login")
def admin_dashboard(request):
    if not is_admin(request.user):
        return redirect("admin_login")

    now = timezone.now()
    current_year = now.year 
    
   
    today_date = now.date()
    today_orders_qs = Order.objects.filter(created_at__date=today_date)
    
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = this_month_start - datetime.timedelta(seconds=1)
    last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
 
    return_stats = get_return_value_stats()
    total_return_value = return_stats['total_value']
    total_return_items = return_stats['total_items']
    total_returns_count = return_stats['count']

    returns_this = ReturnRequest.objects.filter(
        created_at__gte=this_month_start,
        status__in=['approved', 'completed']
    ).count()

    returns_last = ReturnRequest.objects.filter(
        created_at__gte=last_month_start,
        created_at__lte=last_month_end,
        status__in=['approved', 'completed']
    ).count()

    return_counts = {
        'return_requested': ReturnRequest.objects.filter(status='pending').count(),
        'return_approved':  ReturnRequest.objects.filter(status='approved').count(),
        'return_rejected':  ReturnRequest.objects.filter(status='rejected').count(),
        'return_completed': ReturnRequest.objects.filter(status='completed').count(),
        'total_returns':    ReturnRequest.objects.exclude(status='rejected').count(),
    }

    pending_returns = return_counts['return_requested']

    this_month_orders = Order.objects.filter(created_at__gte=this_month_start)
    revenue_this = _get_net_revenue(this_month_orders)

    last_month_orders = Order.objects.filter(
        created_at__gte=last_month_start,
        created_at__lte=last_month_end,
    )
    revenue_last = _get_net_revenue(last_month_orders)
    revenue_all = _get_net_revenue(Order.objects.all())

    items_this = (
        OrderItem.objects
        .filter(order__created_at__gte=this_month_start)
        .exclude(order__status='returned')
        .exclude(order__status__in=EXCLUDED_STATUSES)
        .aggregate(s=Sum("quantity"))["s"] or 0
    )

    items_last = (
        OrderItem.objects
        .filter(
            order__created_at__gte=last_month_start,
            order__created_at__lte=last_month_end,
        )
        .exclude(order__status='returned')
        .exclude(order__status__in=EXCLUDED_STATUSES)
        .aggregate(s=Sum("quantity"))["s"] or 0
    )

    items_total = (
        OrderItem.objects
        .exclude(order__status='returned')
        .exclude(order__status__in=EXCLUDED_STATUSES)
        .aggregate(s=Sum("quantity"))["s"] or 0
    )

    orders_this = (
        Order.objects
        .filter(created_at__gte=this_month_start)
        .exclude(status='returned')
        .exclude(status__in=EXCLUDED_STATUSES)
        .count()
    )

    orders_last = (
        Order.objects
        .filter(
            created_at__gte=last_month_start,
            created_at__lte=last_month_end,
        )
        .exclude(status='returned')
        .exclude(status__in=EXCLUDED_STATUSES)
        .count()
    )

    orders_total = (
        Order.objects
        .exclude(status='returned')
        .exclude(status__in=EXCLUDED_STATUSES)
        .count()
    )

    customers_total = User.objects.filter(is_staff=False).count()
    customers_this = User.objects.filter(
        is_staff=False,
        date_joined__gte=this_month_start
    ).count()
    customers_last = User.objects.filter(
        is_staff=False,
        date_joined__gte=last_month_start,
        date_joined__lte=last_month_end,
    ).count()

    status_counts = {
        "pending": Order.objects.filter(status="pending").count(),
        "confirmed": Order.objects.filter(status="confirmed").count(),
        "processing": Order.objects.filter(status="processing").count(),
        "shipped": Order.objects.filter(status="shipped").count(),
        "delivered": Order.objects.filter(status="delivered").count(),
        "cancelled": Order.objects.filter(status="cancelled").count(),
        "return_requested": Order.objects.filter(status="return_requested").count(),
        "returned": Order.objects.filter(status="returned").count(),
    }

    today_orders_count = today_orders_qs.exclude(status__in=EXCLUDED_STATUSES).count()

    month_labels = ["Jan","Feb","Mar","Apr","May","Jun",
                    "Jul","Aug","Sep","Oct","Nov","Dec"]
    chart_revenue = _monthly_revenue(current_year)

    recent_orders = (
        Order.objects
        .select_related("user")
        .prefetch_related("items")
        .order_by("-created_at")[:8]
    )

    low_stock = (
        ProductVariant.objects
        .select_related("product")
        .filter(stock__gt=0, stock__lte=LOW_STOCK_THRESHOLD)
        .order_by("stock")[:8]
    )
    out_of_stock = ProductVariant.objects.filter(stock=0).count()

    def best_selling(group_field, limit=10):
        return list(
            OrderItem.objects
            .exclude(order__status='returned')
            .exclude(order__status__in=EXCLUDED_STATUSES)
            .exclude(cancel_status='cancelled')
            .exclude(**{f"{group_field}__isnull": True})
            .exclude(**{group_field: ''})
            .values(group_field)
            .annotate(sold=Sum("quantity"), revenue=Sum("line_total"))
            .order_by("-sold")[:limit]
        )

    top_products   = best_selling("product__name", 10)
    top_categories = best_selling("product__category__name", 10)
    top_brands     = best_selling("product__brand", 10)

    revenue_pct = _pct_change(revenue_this, revenue_last)
    orders_pct = _pct_change(orders_this, orders_last)
    items_pct = _pct_change(items_this, items_last)
    customers_pct = _pct_change(customers_this, customers_last)
    returns_pct = _pct_change(returns_this, returns_last)

    context = {
        "revenue": revenue_all,
        "revenue_this": revenue_this,
        "revenue_pct": revenue_pct,

        "orders_count": orders_total,
        "orders_this": orders_this,
        "orders_pct": orders_pct,

        "items_sold": items_total,
        "items_pct": items_pct,

        "customers": customers_total,
        "customers_this": customers_this,
        "customers_pct": customers_pct,

        "total_returns": total_returns_count,
        "returns_this": returns_this,
        "returns_pct": returns_pct,
        "pending_returns": pending_returns,
        "total_return_items": total_return_items,
        "total_return_value": total_return_value,
        "return_counts": return_counts,

        "chart_labels": json.dumps(month_labels),
        "chart_revenue": json.dumps(chart_revenue),

        "status_counts": status_counts,

        "recent_orders": recent_orders,
        "low_stock": low_stock,
        "out_of_stock": out_of_stock,
        "top_products": top_products,
        "top_categories": top_categories,
        "top_brands": top_brands,

        "current_year": current_year,
        "today_orders": today_orders_count,
    }

    return render(request, "dashboard.html", context)

@never_cache
@login_required(login_url="admin_login")
def dashboard_chart_data(request):
    if not is_admin(request.user):
        return JsonResponse({"error": "Forbidden"}, status=403)

    year = request.GET.get("year", timezone.now().year)
    try:
        year = int(year)
    except (ValueError, TypeError):
        year = timezone.now().year

    revenue = _monthly_revenue(year)
    return JsonResponse({"revenue": revenue, "year": year})


@never_cache
@login_required(login_url="admin_login")
def sales_report(request):
    if not is_admin(request.user):
        return redirect("admin_login")

    now = timezone.now()

    filter_type = request.GET.get('filter', 'monthly')
    date_from   = request.GET.get('date_from', '')
    date_to     = request.GET.get('date_to', '')

    if filter_type == 'custom' and date_from and date_to:
        try:
            start = timezone.datetime.strptime(date_from, '%Y-%m-%d').replace(
                hour=0, minute=0, second=0, tzinfo=timezone.get_current_timezone())
            end = timezone.datetime.strptime(date_to, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, tzinfo=timezone.get_current_timezone())
        except ValueError:
            start = now.replace(day=1, hour=0, minute=0, second=0)
            end   = now
    elif filter_type == 'yearly':
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0)
        end   = now
    elif filter_type == 'weekly':
        start = now - datetime.timedelta(days=7)
        end   = now
    elif filter_type == 'daily':
        start = now.replace(hour=0, minute=0, second=0)
        end   = now
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0)
        end   = now

    orders = Order.objects.filter(
        created_at__gte=start,
        created_at__lte=end,
    ).select_related('user').prefetch_related('items').order_by('-created_at')

    total_orders     = orders.count()
    delivered_orders = orders.filter(status='delivered').count()
    cancelled_orders = orders.filter(status='cancelled').count()
    returned_orders  = orders.filter(status__in=['returned', 'return_requested']).count()

    gross_revenue = orders.filter(
        payment_status='paid'
    ).exclude(status='cancelled').aggregate(s=Sum('total'))['s'] or 0

    refund_amount = orders.filter(
        status__in=['returned', 'cancelled'],
        payment_status='paid'
    ).aggregate(s=Sum('total'))['s'] or 0

    net_revenue = float(gross_revenue) - float(refund_amount)

    total_items_sold = OrderItem.objects.filter(
        order__in=orders
    ).exclude(
        order__status__in=['cancelled', 'returned']
    ).aggregate(s=Sum('quantity'))['s'] or 0

    cod_orders    = orders.filter(payment_method='cod').count()
    stripe_orders = orders.filter(payment_method='stripe').count()
    wallet_orders = orders.filter(payment_method='wallet').count()

    top_products = (
        OrderItem.objects
        .filter(order__in=orders)
        .exclude(order__status__in=['cancelled', 'returned'])
        .values('product_name')
        .annotate(sold=Sum('quantity'), revenue=Sum('line_total'))
        .order_by('-sold')[:10]
    )

    return_requests = ReturnRequest.objects.filter(
        created_at__gte=start,
        created_at__lte=end,
    ).select_related('order', 'order_item', 'user')

    context = {
        'orders':           orders,
        'total_orders':     total_orders,
        'delivered_orders': delivered_orders,
        'cancelled_orders': cancelled_orders,
        'returned_orders':  returned_orders,
        'gross_revenue':    gross_revenue,
        'refund_amount':    refund_amount,
        'net_revenue':      net_revenue,
        'total_items_sold': total_items_sold,
        'cod_orders':       cod_orders,
        'stripe_orders':    stripe_orders,
        'wallet_orders':    wallet_orders,
        'top_products':     top_products,
        'return_requests':  return_requests,
        'filter_type':      filter_type,
        'date_from':        date_from,
        'date_to':          date_to,
        'start':            start,
        'end':              end,
        'generated_at':     now,
    }
    return render(request, 'sale_report.html', context)


@never_cache
@login_required(login_url="admin_login")
def sales_report_pdf(request):
    if not is_admin(request.user):
        return redirect("admin_login")

    now = timezone.now()

    filter_type = request.GET.get('filter', 'monthly')
    date_from   = request.GET.get('date_from', '')
    date_to     = request.GET.get('date_to', '')

    if filter_type == 'custom' and date_from and date_to:
        try:
            start = timezone.datetime.strptime(date_from, '%Y-%m-%d').replace(
                hour=0, minute=0, second=0, tzinfo=timezone.get_current_timezone())
            end = timezone.datetime.strptime(date_to, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, tzinfo=timezone.get_current_timezone())
        except ValueError:
            start = now.replace(day=1, hour=0, minute=0, second=0)
            end   = now
    elif filter_type == 'yearly':
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0)
        end   = now
    elif filter_type == 'weekly':
        start = now - datetime.timedelta(days=7)
        end   = now
    elif filter_type == 'daily':
        start = now.replace(hour=0, minute=0, second=0)
        end   = now
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0)
        end   = now

    orders = Order.objects.filter(
        created_at__gte=start,
        created_at__lte=end,
    ).select_related('user').order_by('-created_at')

    total_orders     = orders.count()
    delivered_orders = orders.filter(status='delivered').count()
    cancelled_orders = orders.filter(status='cancelled').count()
    returned_orders  = orders.filter(status__in=['returned','return_requested']).count()

    gross_revenue = orders.filter(
        payment_status='paid'
    ).exclude(status='cancelled').aggregate(s=Sum('total'))['s'] or 0

    refund_amount = orders.filter(
        status__in=['returned','cancelled'],
        payment_status='paid'
    ).aggregate(s=Sum('total'))['s'] or 0

    net_revenue = float(gross_revenue) - float(refund_amount)

    top_products = (
        OrderItem.objects
        .filter(order__in=orders)
        .exclude(order__status__in=['cancelled','returned'])
        .values('product_name')
        .annotate(sold=Sum('quantity'), revenue=Sum('line_total'))
        .order_by('-sold')[:10]
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )

    W, H = landscape(A4)
    usable_w = W - 30*mm

    BLACK  = colors.HexColor('#000000')
    WHITE  = colors.HexColor('#FFFFFF')
    TERRA  = colors.HexColor('#c9967a')
    DARK   = colors.HexColor('#1a1410')
    GRAY   = colors.HexColor('#f5f5f5')
    MUTED  = colors.HexColor('#666666')
    GREEN  = colors.HexColor('#4caf7d')
    RED    = colors.HexColor('#e05252')
    BORDER = colors.HexColor('#dddddd')

    def ps(name, **kw):
        return ParagraphStyle(name, **kw)

    s_title  = ps('t',  fontSize=22, fontName='Helvetica-Bold', textColor=WHITE)
    s_sub    = ps('s',  fontSize=9,  fontName='Helvetica',      textColor=TERRA)
    s_h      = ps('h',  fontSize=9,  fontName='Helvetica-Bold', textColor=WHITE)
    s_b      = ps('b',  fontSize=8,  fontName='Helvetica',      textColor=DARK,  leading=12)
    s_r      = ps('r',  fontSize=8,  fontName='Helvetica',      textColor=DARK,  alignment=TA_RIGHT)
    s_c      = ps('c',  fontSize=8,  fontName='Helvetica',      textColor=MUTED, alignment=TA_CENTER)
    s_label  = ps('l',  fontSize=7,  fontName='Helvetica-Bold', textColor=MUTED,
                  letterSpacing=0.5, spaceAfter=2)
    s_val    = ps('v',  fontSize=13, fontName='Helvetica-Bold', textColor=DARK)
    s_sec    = ps('sc', fontSize=10, fontName='Helvetica-Bold', textColor=DARK,
                  spaceBefore=10, spaceAfter=6)

    story = []

    period_str = f"{start.strftime('%d %b %Y')} — {end.strftime('%d %b %Y')}"
    hdr = Table([[
        Paragraph(
            f'<font name="Helvetica-Bold" size="22" color="#FFFFFF">VESKA</font><br/>'
            f'<font name="Helvetica" size="9" color="#c9967a">Sales Report</font>',
            ps('hh')
        ),
        Paragraph(
            f'<font name="Helvetica-Bold" size="13" color="#FFFFFF">SALES REPORT</font><br/>'
            f'<font name="Helvetica" size="8" color="#c9967a">{period_str}</font><br/>'
            f'<font name="Helvetica" size="7" color="#999999">'
            f'Generated: {now.strftime("%d %b %Y, %I:%M %p")}</font>',
            ps('hr2', alignment=TA_RIGHT)
        ),
    ]], colWidths=[usable_w*0.5, usable_w*0.5])
    hdr.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), DARK),
        ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(hdr)
    story.append(HRFlowable(width=usable_w, thickness=2, color=TERRA, spaceAfter=10))


    def kpi(label, value, color=DARK):
        t = Table([
            [Paragraph(label.upper(), ps(f'kl{label}', fontSize=7,
                fontName='Helvetica-Bold', textColor=MUTED, letterSpacing=0.5, alignment=TA_CENTER))],
            [Paragraph(str(value), ps(f'kv{label}', fontSize=15,
                fontName='Helvetica-Bold', textColor=color, alignment=TA_CENTER))]
        ], colWidths=[usable_w/6 - 4])
        t.setStyle(TableStyle([
            ('ALIGN',        (0,0), (-1,-1), 'CENTER'),
            ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING',   (0,0), (-1,-1), 2),
            ('BOTTOMPADDING',(0,0), (-1,-1), 2),
            ('LEFTPADDING',  (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ]))
        return t

    kpi_table = Table([[
        kpi('Total Orders', total_orders),
        kpi('Delivered', delivered_orders, GREEN),
        kpi('Cancelled', cancelled_orders, RED),
        kpi('Returned', returned_orders, RED),
        kpi('Gross Revenue', f'\u20b9{float(gross_revenue):,.2f}'),
        kpi('Net Revenue', f'\u20b9{net_revenue:,.2f}', GREEN),
    ]], colWidths=[usable_w/6] * 6)

    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), GRAY),
        ('BOX',        (0,0), (-1,-1), 0.5, BORDER),
        ('INNERGRID',  (0,0), (-1,-1), 0.5, BORDER),
        ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 4),
        ('RIGHTPADDING',  (0,0), (-1,-1), 4),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 10))
        
    cod_c    = orders.filter(payment_method='cod').count()
    stripe_c = orders.filter(payment_method='stripe').count()
    wallet_c = orders.filter(payment_method='wallet').count()

    pay_data = [[
        Paragraph('<b>Payment Method</b>', s_h),
        Paragraph('<b>Orders</b>', ps('ph', fontSize=9, fontName='Helvetica-Bold',
                                      textColor=WHITE, alignment=TA_RIGHT)),
    ],[
        Paragraph('Cash on Delivery', s_b),
        Paragraph(str(cod_c), s_r),
    ],[
        Paragraph('Stripe', s_b),
        Paragraph(str(stripe_c), s_r),
    ],[
        Paragraph('Wallet', s_b),
        Paragraph(str(wallet_c), s_r),
    ]]

    prod_data = [[
        Paragraph('<b>Product</b>', s_h),
        Paragraph('<b>Sold</b>', ps('ph2', fontSize=9, fontName='Helvetica-Bold',
                                    textColor=WHITE, alignment=TA_RIGHT)),
        Paragraph('<b>Revenue</b>', ps('ph3', fontSize=9, fontName='Helvetica-Bold',
                                       textColor=WHITE, alignment=TA_RIGHT)),
    ]]
    
    for p in top_products:
        product_name = p.get('product_name')
        if product_name is None:
            product_name = 'Unknown Product'
        else:
            product_name = str(product_name)[:40]
        
        sold = p.get('sold')
        if sold is None:
            sold = 0
        else:
            sold = int(sold)  
        
        revenue = p.get('revenue')
        if revenue is None:
            revenue = 0
        else:
            revenue = float(revenue)  
        prod_data.append([
            Paragraph(product_name, s_b),
            Paragraph(str(sold), s_r),
            Paragraph(f"₹{revenue:,.2f}", s_r),
        ])

    col_w = [
        usable_w*0.22,  
        usable_w*0.18,  
        usable_w*0.10,  
        usable_w*0.10,  
        usable_w*0.10,  
        usable_w*0.10,  
        usable_w*0.10,  
        usable_w*0.10,  
    ]

    rows = [[
        Paragraph('<b>Order</b>',      s_h),
        Paragraph('<b>Customer</b>',     s_h),
        Paragraph('<b>Date</b>',         s_h),
        Paragraph('<b>Status</b>',       s_h),
        Paragraph('<b>Payment</b>',      s_h),
        Paragraph('<b>Pay Status</b>',   s_h),
        Paragraph('<b>Items</b>',        ps('ih', fontSize=9, fontName='Helvetica-Bold',
                                            textColor=WHITE, alignment=TA_RIGHT)),
        Paragraph('<b>Total</b>',        ps('th', fontSize=9, fontName='Helvetica-Bold',
                                            textColor=WHITE, alignment=TA_RIGHT)),
    ]]


    for o in orders[:50]: 
        order_id = str(o.uuid)[:18] if o.uuid else 'N/A'
        
        customer_name = o.full_name or ''
        customer_email = getattr(o.user, 'email', '') if o.user else ''
        customer_info = f"{customer_name}<br/><font size='6' color='#888888'>{customer_email}</font>"
        
        order_date = o.created_at.strftime('%d %b %Y') if o.created_at else 'N/A'
        order_status = o.status.title() if o.status else 'N/A'
        payment_method = o.payment_method.upper() if o.payment_method else 'N/A'
        payment_status = o.payment_status.title() if o.payment_status else 'N/A'
        item_count = str(o.items.count()) if hasattr(o, 'items') else '0'
        total_amount = f'₹{float(o.total):,.2f}' if o.total is not None else '₹0.00'
        
        rows.append([
            Paragraph(order_id, ps('ob', fontSize=7, fontName='Helvetica',
                                    textColor=DARK)),  
            Paragraph(customer_info, ps('cb', fontSize=7.5, fontName='Helvetica', 
                                    textColor=DARK, leading=10)),
            Paragraph(order_date, s_b),
            Paragraph(order_status, s_b),
            Paragraph(payment_method, s_b),
            Paragraph(payment_status, s_b),
            Paragraph(item_count, s_r),
            Paragraph(total_amount, s_r),
        ])

    order_tbl = Table(rows, colWidths=col_w, repeatRows=1)
    order_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  DARK),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [WHITE, GRAY]),
        ('GRID',          (0,0), (-1,-1), 0.3, BORDER),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 12),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING',   (0,0), (-1,-1), 5),
        ('RIGHTPADDING',  (0,0), (-1,-1), 5),
    ]))
    story.append(order_tbl)

    if total_orders > 50:
        story.append(Paragraph(
            f'* Showing first 50 of {total_orders} orders. '
            f'Use date filters to narrow the range.',
            ps('note', fontSize=7, fontName='Helvetica', textColor=MUTED, spaceBefore=4)
        ))

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width=usable_w, thickness=0.5, color=BORDER, spaceAfter=6))
    story.append(Paragraph(
        f'Veska Admin · Sales Report · Generated {now.strftime("%d %b %Y, %I:%M %p")}',
        ps('ft', fontSize=7, fontName='Helvetica', textColor=MUTED, alignment=TA_CENTER)
    ))

    doc.build(story)
    buf.seek(0)

    filename = f"Veska_Sales_Report_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.pdf"
    response = HttpResponse(buf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@never_cache
@login_required(login_url="admin_login")
def dashboard_report_download(request):
    if not is_admin(request.user):
        return redirect("admin_login")
    

    now = timezone.now()
    current_year = now.year
    
    start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    end = now
    
    orders = Order.objects.filter(
        created_at__gte=start,
        created_at__lte=end,
    ).select_related('user').prefetch_related('items').order_by('-created_at')
    
    total_orders = orders.count()
    delivered_orders = orders.filter(status='delivered').count()
    cancelled_orders = orders.filter(status='cancelled').count()
    returned_orders = orders.filter(status__in=['returned', 'return_requested']).count()
    
    gross_revenue = orders.filter(
        payment_status='paid'
    ).exclude(status='cancelled').aggregate(s=Sum('total'))['s'] or 0
    
    refund_amount = orders.filter(
        status__in=['returned', 'cancelled'],
        payment_status='paid'
    ).aggregate(s=Sum('total'))['s'] or 0
    
    net_revenue = float(gross_revenue) - float(refund_amount)
    
    total_items_sold = OrderItem.objects.filter(
        order__in=orders
    ).exclude(
        order__status__in=['cancelled', 'returned']
    ).aggregate(s=Sum('quantity'))['s'] or 0
    
    cod_orders = orders.filter(payment_method='cod').count()
    stripe_orders = orders.filter(payment_method='stripe').count()
    wallet_orders = orders.filter(payment_method='wallet').count()
    
    top_products = (
        OrderItem.objects
        .filter(order__in=orders)
        .exclude(order__status__in=['cancelled', 'returned'])
        .values('product_name')
        .annotate(sold=Sum('quantity'), revenue=Sum('line_total'))
        .order_by('-sold')[:10]
    )
    
    monthly_data = []
    for month in range(1, 13):
        month_orders = Order.objects.filter(
            created_at__year=current_year,
            created_at__month=month,
        )
        month_revenue = _get_net_revenue(month_orders)
        monthly_data.append({
            'month': f"{month:02d}",
            'revenue': float(month_revenue)
        })
    
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )
    
    W, H = landscape(A4)
    usable_w = W - 30*mm
    
    BLACK = colors.HexColor('#000000')
    WHITE = colors.HexColor('#FFFFFF')
    TERRA = colors.HexColor('#c9967a')
    DARK = colors.HexColor('#1a1410')
    GRAY = colors.HexColor('#f5f5f5')
    MUTED = colors.HexColor('#666666')
    GREEN = colors.HexColor('#4caf7d')
    RED = colors.HexColor('#e05252')
    BORDER = colors.HexColor('#dddddd')
    
    def ps(name, **kw):
        return ParagraphStyle(name, **kw)
    
    s_title = ps('t', fontSize=22, fontName='Helvetica-Bold', textColor=WHITE)
    s_sub = ps('s', fontSize=9, fontName='Helvetica', textColor=TERRA)
    s_h = ps('h', fontSize=9, fontName='Helvetica-Bold', textColor=WHITE)
    s_b = ps('b', fontSize=8, fontName='Helvetica', textColor=DARK, leading=12)
    s_r = ps('r', fontSize=8, fontName='Helvetica', textColor=DARK, alignment=TA_RIGHT)
    s_c = ps('c', fontSize=8, fontName='Helvetica', textColor=MUTED, alignment=TA_CENTER)
    s_label = ps('l', fontSize=7, fontName='Helvetica-Bold', textColor=MUTED,
                 letterSpacing=0.5, spaceAfter=2)
    s_val = ps('v', fontSize=13, fontName='Helvetica-Bold', textColor=DARK)
    s_sec = ps('sc', fontSize=10, fontName='Helvetica-Bold', textColor=DARK,
               spaceBefore=10, spaceAfter=6)
    
    story = []
    
    period_str = f"January - {end.strftime('%B %Y')}"
    hdr = Table([[
        Paragraph(
            f'<font name="Helvetica-Bold" size="22" color="#FFFFFF">VESKA</font><br/>'
            f'<font name="Helvetica" size="9" color="#c9967a">Annual Sales Report {current_year}</font>',
            ps('hh')
        ),
        Paragraph(
            f'<font name="Helvetica-Bold" size="13" color="#FFFFFF">SALES REPORT</font><br/>'
            f'<font name="Helvetica" size="8" color="#c9967a">{period_str}</font><br/>'
            f'<font name="Helvetica" size="7" color="#999999">'
            f'Generated: {now.strftime("%d %b %Y, %I:%M %p")}</font>',
            ps('hr2', alignment=TA_RIGHT)
        ),
    ]], colWidths=[usable_w*0.5, usable_w*0.5])
    hdr.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), DARK),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(hdr)
    story.append(HRFlowable(width=usable_w, thickness=2, color=TERRA, spaceAfter=10))
    
    def kpi(label, value, color=DARK):
        return [
            Paragraph(label.upper(), ps(f'kl{label}', fontSize=7, fontName='Helvetica-Bold',
                                        textColor=MUTED, letterSpacing=0.5)),
            Paragraph(str(value), ps(f'kv{label}', fontSize=15, fontName='Helvetica-Bold',
                                     textColor=color)),
        ]
    
    kpi_table = Table([
        [
            Table([kpi('Total Orders', total_orders)], colWidths=[usable_w/10]),
            Table([kpi('Delivered', delivered_orders, GREEN)], colWidths=[usable_w/10]),
            Table([kpi('Cancelled', cancelled_orders, RED)], colWidths=[usable_w/10]),
            Table([kpi('Returned', returned_orders, RED)], colWidths=[usable_w/10]),
            Table([kpi('Gross Revenue', f'₹{float(gross_revenue):,.2f}')], colWidths=[usable_w/9]),
            Table([kpi('Net Revenue', f'₹{net_revenue:,.2f}', GREEN)], colWidths=[usable_w/9]),
        ]
    ], colWidths=[usable_w/6]*6)
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), GRAY),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.5, BORDER),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 10))
    
    story.append(Paragraph('Monthly Revenue Breakdown', ps('sec2',
        fontSize=10, fontName='Helvetica-Bold', textColor=DARK,
        spaceBefore=4, spaceAfter=6)))
    
    month_data = [[
        Paragraph('<b>Month</b>', s_h),
        Paragraph('<b>Revenue</b>', ps('ph', fontSize=9, fontName='Helvetica-Bold',
                                       textColor=WHITE, alignment=TA_RIGHT)),
    ]]
    
    total_revenue = 0
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    s_center = ps('rc', fontSize=8, fontName='Helvetica', textColor=DARK, alignment=TA_CENTER)

    for i, data in enumerate(monthly_data):
        rev = data['revenue']
        total_revenue += rev
        month_data.append([
            Paragraph(month_names[i], s_b),
            Paragraph(f'\u20b9{rev:,.2f}', s_center),  
        ])
    
    month_data.append([
        Paragraph('<b>TOTAL</b>', ps('total', fontSize=9, fontName='Helvetica-Bold', textColor=DARK)),
        Paragraph(f'<b>₹{total_revenue:,.2f}</b>', ps('total_r', fontSize=9, fontName='Helvetica-Bold', 
                                                      textColor=DARK, alignment=TA_RIGHT)),
    ])
    
    month_tbl = Table(month_data, colWidths=[usable_w*0.5, usable_w*0.5])
    month_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), DARK),
        ('ROWBACKGROUNDS', (0,1), (-1,-2), [WHITE, GRAY]),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e8e0d8')),
        ('GRID', (0,0), (-1,-1), 0.3, BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 7),
    ]))
    story.append(month_tbl)
    story.append(Spacer(1, 10))
    
    story.append(Paragraph('Payment Methods & Top Products', ps('sec',
        fontSize=10, fontName='Helvetica-Bold', textColor=DARK,
        spaceBefore=4, spaceAfter=6)))
    
    pay_data = [[
        Paragraph('<b>Payment Method</b>', s_h),
        Paragraph('<b>Orders</b>', ps('ph', fontSize=9, fontName='Helvetica-Bold',
                                      textColor=WHITE, alignment=TA_RIGHT)),
    ], [
        Paragraph('Cash on Delivery', s_b),
        Paragraph(str(cod_orders), s_r),
    ], [
        Paragraph('Stripe', s_b),
        Paragraph(str(stripe_orders), s_r),
    ], [
        Paragraph('Wallet', s_b),
        Paragraph(str(wallet_orders), s_r),
    ]]
    
    prod_data = [[
        Paragraph('<b>Product</b>', s_h),
        Paragraph('<b>Sold</b>', ps('ph2', fontSize=9, fontName='Helvetica-Bold',
                                    textColor=WHITE, alignment=TA_RIGHT)),
        Paragraph('<b>Revenue</b>', ps('ph3', fontSize=9, fontName='Helvetica-Bold',
                                       textColor=WHITE, alignment=TA_RIGHT)),
    ]]
    for p in top_products:
        prod_data.append([
            Paragraph(str(p.get('product_name') or 'Unknown Product')[:40], s_b),
            Paragraph(str(p.get('sold') or 0), s_r),
            Paragraph(f"₹{float(p.get('revenue') or 0):,.2f}", s_r),
        ])
    
    pay_tbl = Table(pay_data, colWidths=[usable_w*0.20, usable_w*0.10])
    prod_tbl = Table(prod_data, colWidths=[usable_w*0.42, usable_w*0.12, usable_w*0.14])
    
    for t in [pay_tbl, prod_tbl]:
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), DARK),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, GRAY]),
            ('GRID', (0,0), (-1,-1), 0.3, BORDER),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 7),
        ]))
    
    side_by_side = Table(
        [[pay_tbl, '', prod_tbl]],
        colWidths=[usable_w*0.32, 6, usable_w*0.68]
    )
    story.append(side_by_side)
    story.append(Spacer(1, 10))
    
    story.append(HRFlowable(width=usable_w, thickness=0.5, color=BORDER, spaceAfter=6))
    story.append(Paragraph('Recent Orders (Last 20)', ps('sec2',
        fontSize=10, fontName='Helvetica-Bold', textColor=DARK,
        spaceBefore=4, spaceAfter=6)))
    
    col_w = [
        usable_w*0.20,   
        usable_w*0.18, 
        usable_w*0.08, 
        usable_w*0.10,  
        usable_w*0.08,  
        usable_w*0.08,  
        usable_w*0.08,  
    ]
    
    rows = [[
        Paragraph('<b>Order</b>', s_h),
        Paragraph('<b>Customer</b>', s_h),
        Paragraph('<b>Date</b>', s_h),
        Paragraph('<b>Status</b>', s_h),
        Paragraph('<b>Payment</b>', s_h),
        Paragraph('<b>Items</b>', ps('ih', fontSize=9, fontName='Helvetica-Bold',
                                     textColor=WHITE, alignment=TA_RIGHT)),
        Paragraph('<b>Total</b>', ps('th', fontSize=9, fontName='Helvetica-Bold',
                                     textColor=WHITE, alignment=TA_RIGHT)),
    ]]
    
    for o in orders[:20]:
        rows.append([
            Paragraph(str(o.uuid)[:18], ps('ob', fontSize=7, fontName='Helvetica',
                                            textColor=colors.HexColor('#c9967a'))),
            Paragraph(f"{o.full_name}", ps('cb', fontSize=7.5, fontName='Helvetica', 
                                           textColor=DARK)),
            Paragraph(o.created_at.strftime('%d %b'), s_b),
            Paragraph(o.status.title(), s_b),
            Paragraph(o.payment_method.upper(), s_b),
            Paragraph(str(o.items.count()), s_r),
            Paragraph(f'₹{float(o.total):,.2f}', s_r),
        ])
    
    order_tbl = Table(rows, colWidths=col_w, repeatRows=1)
    order_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), DARK),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, GRAY]),
        ('GRID', (0,0), (-1,-1), 0.3, BORDER),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(order_tbl)
    
    if total_orders > 20:
        story.append(Paragraph(
            f'* Showing first 20 of {total_orders} orders.',
            ps('note', fontSize=7, fontName='Helvetica', textColor=MUTED, spaceBefore=4)
        ))
    
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width=usable_w, thickness=0.5, color=BORDER, spaceAfter=6))
    story.append(Paragraph(
        f'Veska Admin · Annual Sales Report {current_year} · Generated {now.strftime("%d %b %Y, %I:%M %p")}',
        ps('ft', fontSize=7, fontName='Helvetica', textColor=MUTED, alignment=TA_CENTER)
    ))
    
    try:
        doc.build(story)
    except Exception as e:
        print("PDF ERROR:", e)

        for item in story:
            print(type(item))

        raise
    buf.seek(0)
    
    filename = f"Veska_Annual_Report_{current_year}.pdf"
    response = HttpResponse(buf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response