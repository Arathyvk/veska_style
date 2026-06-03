import json
import datetime
from decimal import Decimal

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.utils import timezone

from order_user.models import Order, OrderItem
from product_admin.models import Product
from customers.models import Address  
from django.contrib.auth import get_user_model

User = get_user_model()

LOW_STOCK_THRESHOLD = 5


def is_admin(user):
    return user.is_authenticated and user.is_staff


def _pct_change(current, previous):
    if not previous:
        return "+100%" if current else "0%"
    change = ((current - previous) / previous) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


def _monthly_revenue(year):
    data = []
    for month in range(1, 13):
        total = (
            Order.objects.filter(
                created_at__year=year,
                created_at__month=month,
                payment_status="paid",
            ).aggregate(s=Sum("total"))["s"]
            or 0
        )
        data.append(float(total))
    return data


@never_cache
@login_required(login_url="admin_login")
def admin_dashboard(request):
    if not is_admin(request.user):
        return redirect("admin_login")

    now = timezone.now()
    current_year = now.year
    current_month = now.month

    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = this_month_start - datetime.timedelta(seconds=1)
    last_month_start = last_month_end.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    revenue_this = (
        Order.objects.filter(
            created_at__gte=this_month_start, payment_status="paid"
        ).aggregate(s=Sum("total"))["s"]
        or 0
    )
    revenue_last = (
        Order.objects.filter(
            created_at__gte=last_month_start,
            created_at__lte=last_month_end,
            payment_status="paid",
        ).aggregate(s=Sum("total"))["s"]
        or 0
    )
    revenue_all = (
        Order.objects.filter(payment_status="paid").aggregate(s=Sum("total"))["s"] or 0
    )

    orders_this = Order.objects.filter(created_at__gte=this_month_start).count()
    orders_last = Order.objects.filter(
        created_at__gte=last_month_start, created_at__lte=last_month_end
    ).count()
    orders_total = Order.objects.count()

    items_this = (
        OrderItem.objects.filter(
            order__created_at__gte=this_month_start
        ).aggregate(s=Sum("quantity"))["s"]
        or 0
    )
    items_last = (
        OrderItem.objects.filter(
            order__created_at__gte=last_month_start,
            order__created_at__lte=last_month_end,
        ).aggregate(s=Sum("quantity"))["s"]
        or 0
    )

    customers_this = User.objects.filter(
        is_staff=False, date_joined__gte=this_month_start
    ).count()
    customers_last = User.objects.filter(
        is_staff=False,
        date_joined__gte=last_month_start,
        date_joined__lte=last_month_end,
    ).count()
    customers_total = User.objects.filter(is_staff=False).count()

    status_counts = {}
    for status, _ in [
        ("pending", ""),
        ("confirmed", ""),
        ("processing", ""),
        ("shipped", ""),
        ("delivered", ""),
        ("cancelled", ""),
        ("return_requested", ""),
        ("returned", ""),
    ]:
        status_counts[status] = Order.objects.filter(status=status).count()

    month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    chart_revenue = _monthly_revenue(current_year)

    recent_orders = (
        Order.objects.select_related("user")
        .prefetch_related("items")
        .order_by("-created_at")[:8]
    )

    low_stock = Product.objects.filter(
        stock__gt=0, stock__lte=LOW_STOCK_THRESHOLD
    ).order_by("stock")[:8]

    out_of_stock = Product.objects.filter(stock=0).count()

    top_products = (
        OrderItem.objects.values("product__name")
        .annotate(sold=Sum("quantity"))
        .order_by("-sold")[:5]
    )

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_orders = Order.objects.filter(created_at__gte=today_start).count()
    today_revenue = (
        Order.objects.filter(
            created_at__gte=today_start, payment_status="paid"
        ).aggregate(s=Sum("total"))["s"]
        or 0
    )

    context = {
        "revenue": revenue_all,
        "revenue_this": revenue_this,
        "revenue_pct": _pct_change(revenue_this, revenue_last),
        "orders_count": orders_total,
        "orders_this": orders_this,
        "orders_pct": _pct_change(orders_this, orders_last),
        "items_sold": items_this,
        "items_pct": _pct_change(items_this, items_last),
        "customers": customers_total,
        "customers_this": customers_this,
        "customers_pct": _pct_change(customers_this, customers_last),
        "chart_labels": json.dumps(month_labels),
        "chart_revenue": json.dumps(chart_revenue),
        "status_counts": status_counts,
        "recent_orders": recent_orders,
        "low_stock": low_stock,
        "out_of_stock": out_of_stock,
        "top_products": top_products,
        "current_year": current_year,
        "today_orders": today_orders,
        "today_revenue": today_revenue,
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