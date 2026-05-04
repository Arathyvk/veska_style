from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Q
from datetime import datetime
from django.utils import timezone as tz
from django.http import JsonResponse


from coupon_admin.models import Coupon
from product_admin.models import Product
from product_admin.views import is_admin

CATEGORY_CHOICES = [
    ('Formal', 'Formal'), ('Casual', 'Casual'), ('Party', 'Party'),
    ('Sports', 'Sports'), ('Ethnic', 'Ethnic'), ('Sandal', 'Sandal'),
]


@login_required(login_url='admin_login')
def admin_coupon_list(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    qs = Coupon.objects.all()
    q  = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(description__icontains=q))

    active_f = request.GET.get('active', '')
    if active_f == '1':
        qs = qs.filter(is_active=True)
    elif active_f == '0':
        qs = qs.filter(is_active=False)

    paginator = Paginator(qs, 15)
    page_obj  = paginator.get_page(request.GET.get('page', 1))
    params    = request.GET.copy(); params.pop('page', None)

    return render(request, 'admin_coupon_list.html', {
        'page_obj': page_obj, 'query': q, 'active_filter': active_f,
        'params_str': params.urlencode(), 'now': timezone.now(),
        'total_count': paginator.count,
    })


@login_required(login_url='admin_login')
def admin_coupon_add(request):
    if not is_admin(request.user):
        return redirect('admin_login')
    return _coupon_form(request, coupon=None)


@login_required(login_url='admin_login')
def admin_coupon_edit(request, pk):
    if not is_admin(request.user):
        return redirect('admin_login')
    coupon = get_object_or_404(Coupon, pk=pk)
    return _coupon_form(request, coupon=coupon)


def _coupon_form(request, coupon):
    all_products = Product.objects.filter(is_active=True).only('id', 'name', 'category')
    errors = {}

    if request.method == 'POST':
        data = request.POST
        code          = data.get('code', '').strip().upper()
        description   = data.get('description', '').strip()
        discount_type = data.get('discount_type', '')
        value_str     = data.get('value', '').strip()
        max_disc_str  = data.get('max_discount', '').strip()
        min_order_str = data.get('min_order_value', '0').strip()
        apply_to      = data.get('apply_to', 'all')
        categories    = data.getlist('categories')
        product_ids   = data.getlist('products')
        is_active     = bool(data.get('is_active'))
        valid_from_s  = data.get('valid_from', '').strip()
        valid_until_s = data.get('valid_until', '').strip()
        usage_limit_s = data.get('usage_limit', '').strip()
        per_user_s    = data.get('per_user_limit', '1').strip()

        if not code:
            errors['code'] = 'Code is required.'
        elif Coupon.objects.filter(code=code).exclude(pk=coupon.pk if coupon else None).exists():
            errors['code'] = f'Code "{code}" already exists.'
        if not discount_type:
            errors['discount_type'] = 'Select a discount type.'
        try:
            value = Decimal(value_str)
            if value <= 0: raise ValueError
        except Exception:
            errors['value'] = 'Enter a valid positive number.'
            value = Decimal('0')
        try:
            min_order_value = Decimal(min_order_str) if min_order_str else Decimal('0')
        except Exception:
            errors['min_order_value'] = 'Enter a valid amount.'
            min_order_value = Decimal('0')
        try:
            max_discount = Decimal(max_disc_str) if max_disc_str else None
        except Exception:
            max_discount = None
        try:
            per_user_limit = int(per_user_s) if per_user_s else 1
        except ValueError:
            per_user_limit = 1
        try:
            usage_limit = int(usage_limit_s) if usage_limit_s else None
        except ValueError:
            usage_limit = None

        def parse_dt(s):
            if not s: return None

            try:
                dt = datetime.strptime(s, '%Y-%m-%dT%H:%M')
                return tz.make_aware(dt)
            except Exception:
                return None

        valid_from_dt  = parse_dt(valid_from_s) or timezone.now()
        valid_until_dt = parse_dt(valid_until_s)

        if not errors:
            kwargs = dict(
                code=code, description=description, discount_type=discount_type,
                value=value, max_discount=max_discount, min_order_value=min_order_value,
                apply_to=apply_to, categories=categories, is_active=is_active,
                valid_from=valid_from_dt, valid_until=valid_until_dt,
                usage_limit=usage_limit, per_user_limit=per_user_limit,
            )
            if coupon:
                for k, v in kwargs.items():
                    setattr(coupon, k, v)
                coupon.save()
                coupon.products.set(product_ids)
                messages.success(request, f'Coupon "{coupon.code}" updated.')
            else:
                coupon = Coupon.objects.create(**kwargs)
                coupon.products.set(product_ids)
                messages.success(request, f'Coupon "{coupon.code}" created.')
            return redirect('admin_coupon_list')

    def fmt_dt(dt):
        if not dt: return ''
        return tz.localtime(dt).strftime('%Y-%m-%dT%H:%M')

    selected_products = list(coupon.products.values_list('id', flat=True)) if coupon else []
    selected_cats     = coupon.categories if coupon else []

    return render(request, 'admin_coupon_form.html', {
        'action': 'edit' if coupon else 'add',
        'coupon': coupon, 'errors': errors,
        'all_products': all_products,
        'all_categories': CATEGORY_CHOICES,
        'selected_products': selected_products,
        'selected_cats': selected_cats,
        'valid_from_str':  fmt_dt(coupon.valid_from)  if coupon else '',
        'valid_until_str': fmt_dt(coupon.valid_until) if coupon else '',
    })


@require_POST
@login_required(login_url='admin_login')
def admin_coupon_toggle(request, pk):
    if not is_admin(request.user):
        return JsonResponse({'ok': False}, status=403)
    coupon = get_object_or_404(Coupon, pk=pk)
    coupon.is_active = not coupon.is_active
    coupon.save(update_fields=['is_active'])
    return JsonResponse({'ok': True, 'is_active': coupon.is_active})


@require_POST
@login_required(login_url='admin_login')
def admin_coupon_delete(request, pk):
    if not is_admin(request.user):
        return redirect('admin_login')
    coupon = get_object_or_404(Coupon, pk=pk)
    code   = coupon.code
    coupon.delete()
    messages.success(request, f'Coupon "{code}" deleted.')
    return redirect('admin_coupon_list')