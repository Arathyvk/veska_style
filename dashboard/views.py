import json
import datetime

from django.db import models
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from django.db.models import Sum
from django.utils import timezone

from order_user.models import Order, OrderItem
from product_admin.models import Product
from django.contrib.auth import get_user_model
from return_admin.models import ReturnRequest

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
    total_return_items = 0
    
    for ret in approved_returns:
        if ret.order_item:
            total_return_value += float(ret.order_item.line_total or 0)
            total_return_items += ret.order_item.quantity or 0
        elif ret.order:
            total_return_value += float(ret.order.total or 0)
    
    return {
        'total_value': total_return_value,
        'total_items': total_return_items,
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

    
    print("\n" + "="*60)
    print("TODAY'S REVENUE DEBUG")
    print("="*60)
    print(f"Current time (now): {now}")
    print(f"Today's date: {today_date}")
    print(f"Total orders today: {today_orders_qs.count()}")
    
    if today_orders_qs.exists():
        print("\n--- All Orders Today ---")
        for order in today_orders_qs:
            print(f"Order: {order.order_number}")
            print(f"  Total: ₹{order.total}")
            print(f"  Status: {order.status}")
            print(f"  Payment Status: {order.payment_status}")
            print(f"  Payment Method: {order.payment_method}")
            print(f"  Created: {order.created_at}")
            print("---")
    
    


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

    low_stock = list(
        Product.objects
        .filter(stock__gt=0, stock__lte=LOW_STOCK_THRESHOLD)
        .order_by("stock")[:8]
        .values('id', 'name', 'stock')
    )
    out_of_stock = Product.objects.filter(stock=0).count()

    top_products = list(
        OrderItem.objects
        .exclude(order__status='returned')
        .exclude(order__status__in=EXCLUDED_STATUSES)
        .values("product__name")
        .annotate(sold=Sum("quantity"))
        .order_by("-sold")[:5]
    )

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