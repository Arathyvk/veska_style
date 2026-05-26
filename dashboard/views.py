from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncMonth, TruncDate
from django.utils import timezone
from django.http import JsonResponse

import datetime
import json

from order_user.models import Order, OrderItem
from product_admin.models import Product
from category_admin.models import Category
from customers.models import Address          


def is_admin(user):
    return user.is_authenticated and user.is_staff


def _pct_change(current, previous):
    if not previous:
        return '+100%' if current else '0%'
    pct = round((current - previous) / previous * 100)
    return f'+{pct}%' if pct >= 0 else f'{pct}%'



@never_cache
@login_required(login_url='admin_login')
def admin_dashboard(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    now   = timezone.now()
    today = now.date()

    this_month_start = today.replace(day=1)
    last_month_end   = this_month_start - datetime.timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    this_year  = today.year
    last_year  = this_year - 1

    all_orders       = Order.objects.all()
    paid_orders      = all_orders.filter(payment_status='paid')
    this_month_paid  = paid_orders.filter(created_at__date__gte=this_month_start)
    last_month_paid  = paid_orders.filter(
        created_at__date__gte=last_month_start,
        created_at__date__lte=last_month_end,
    )

    revenue_this  = this_month_paid.aggregate(s=Sum('total'))['s'] or 0
    revenue_last  = last_month_paid.aggregate(s=Sum('total'))['s'] or 0
    revenue_pct   = _pct_change(revenue_this, revenue_last)

    orders_this   = this_month_paid.count()
    orders_last   = last_month_paid.count()
    orders_pct    = _pct_change(orders_this, orders_last)

    items_this = (
        OrderItem.objects
        .filter(order__in=this_month_paid)
        .aggregate(s=Sum('quantity'))['s'] or 0
    )
    items_last = (
        OrderItem.objects
        .filter(order__in=last_month_paid)
        .aggregate(s=Sum('quantity'))['s'] or 0
    )
    items_pct  = _pct_change(items_this, items_last)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    customers_total = User.objects.filter(is_staff=False).count()
    customers_this  = User.objects.filter(
        is_staff=False,
        date_joined__date__gte=this_month_start,
    ).count()
    customers_last  = User.objects.filter(
        is_staff=False,
        date_joined__date__gte=last_month_start,
        date_joined__date__lte=last_month_end,
    ).count()
    customers_pct   = _pct_change(customers_this, customers_last)

    monthly_qs = (
        paid_orders
        .filter(created_at__year=this_year)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Sum('total'))
        .order_by('month')
    )
    monthly_map = {r['month'].month: float(r['total']) for r in monthly_qs}
    chart_labels  = ['Jan','Feb','Mar','Apr','May','Jun',
                     'Jul','Aug','Sep','Oct','Nov','Dec']
    chart_revenue = [monthly_map.get(m, 0) for m in range(1, 13)]

    thirty_ago = today - datetime.timedelta(days=29)
    daily_qs = (
        all_orders
        .filter(created_at__date__gte=thirty_ago)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(cnt=Count('id'))
        .order_by('day')
    )
    daily_map = {r['day']: r['cnt'] for r in daily_qs}
    daily_labels = [
        (thirty_ago + datetime.timedelta(days=i)).strftime('%d %b')
        for i in range(30)
    ]
    daily_orders = [
        daily_map.get(thirty_ago + datetime.timedelta(days=i), 0)
        for i in range(30)
    ]

    recent_orders = (
        all_orders
        .select_related('user')
        .prefetch_related('items')
        .order_by('-created_at')[:8]
    )

    top_products = (
        OrderItem.objects
        .values('product__name', 'product__uuid')
        .annotate(sold=Sum('quantity'), revenue=Sum('unit_price'))
        .order_by('-sold')[:5]
    )

    status_counts = {
        'pending':    all_orders.filter(status='pending').count(),
        'confirmed':  all_orders.filter(status='confirmed').count(),
        'processing': all_orders.filter(status='processing').count(),
        'shipped':    all_orders.filter(status='shipped').count(),
        'delivered':  all_orders.filter(status='delivered').count(),
        'cancelled':  all_orders.filter(status='cancelled').count(),
    }

    LOW = 5
    low_stock_products = (
        Product.objects
        .filter(is_active=True, stock__lte=LOW, stock__gt=0)
        .order_by('stock')[:6]
    )
    out_of_stock = Product.objects.filter(is_active=True, stock=0).count()

    context = {
        'revenue':       revenue_this,
        'revenue_pct':   revenue_pct,
        'orders_count':  orders_this,
        'orders_pct':    orders_pct,
        'items_sold':    items_this,
        'items_pct':     items_pct,
        'customers':     customers_total,
        'customers_pct': customers_pct,

        'chart_labels':   json.dumps(chart_labels),
        'chart_revenue':  json.dumps(chart_revenue),
        'daily_labels':   json.dumps(daily_labels),
        'daily_orders':   json.dumps(daily_orders),

        'recent_orders':    recent_orders,
        'top_products':     top_products,
        'status_counts':    status_counts,
        'low_stock':        low_stock_products,
        'out_of_stock':     out_of_stock,

        'current_year':  this_year,
        'now':           now,
    }
    return render(request, 'dashboard.html', context)



@never_cache
@login_required(login_url='admin_login')
def dashboard_chart_data(request):
    if not is_admin(request.user):
        return JsonResponse({'error': 'forbidden'}, status=403)

    year = int(request.GET.get('year', timezone.now().year))

    monthly_qs = (
        Order.objects
        .filter(payment_status='paid', created_at__year=year)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Sum('total'))
        .order_by('month')
    )
    monthly_map   = {r['month'].month: float(r['total']) for r in monthly_qs}
    chart_revenue = [monthly_map.get(m, 0) for m in range(1, 13)]

    return JsonResponse({'revenue': chart_revenue, 'year': year})