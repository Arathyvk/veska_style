from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.timezone import now
import datetime

from return_admin.models import ReturnRequest, RETURN_DAYS


LOW_STOCK = 5

NON_RETURNABLE = ['hygiene','personalised', 'final_sale']




def is_admin(user):
    return user.is_authenticated and user.is_staff


print("ADMIN RETURN LIST VIEW CALLED")




@never_cache
@login_required(login_url='admin_login')
def admin_return_list(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    status_filter = request.GET.get('status', '').strip()
    query = request.GET.get('q', '').strip()

 
    qs = ReturnRequest.objects.select_related(
        'user',
        'order',
        'order_item',
        'order_item__product'
    ).order_by('-created_at')

   
    if status_filter:
        qs = qs.filter(status=status_filter)

 
    if query:
        qs = qs.filter(
            Q(user__email__icontains=query) |
            Q(user__first_name__icontains=query) |
            Q(order__id__icontains=query) |
            Q(order_item__product__name__icontains=query)
        )

    qs = qs.distinct()


    stats = qs.aggregate(
        total=Count('id', distinct=True),
        pending=Count('id', filter=Q(status='pending')),
        approved=Count('id', filter=Q(status='approved')),
        rejected=Count('id', filter=Q(status='rejected')),
    )

    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

 
    current = page_obj.number
    num_pages = paginator.num_pages

    visible = {1, num_pages}

    for i in range(current - 2, current + 3):
        if 1 <= i <= num_pages:
            visible.add(i)

    page_range = []
    prev = None

    for p in sorted(visible):
        if prev and p - prev > 1:
            page_range.append(None)
        page_range.append(p)
        prev = p

 
    print("QS COUNT:", qs.count())
    print("PAGE:", page_obj.number)

   
    return render(request, 'admin_return_list.html', {
        'returns': page_obj,
        'stats': stats,
        'status_filter': status_filter,
        'query': query,
        'page_range': page_range,
    })



@never_cache
@login_required(login_url='admin_login')
def admin_return_detail(request, pk):
    if not is_admin(request.user):
        return redirect('admin_login')

    ret = get_object_or_404(
        ReturnRequest.objects.select_related(
            'user',
            'order',
            'order_item',
            'order_item__product',
            'order_item__variant'
        ),
        pk=pk
    )

    proof_images = ret.proof_images.all()
    internal_notes = []

    if ret.order.delivered_at:
        return_deadline = ret.order.delivered_at + datetime.timedelta(days=RETURN_DAYS)
    else:
        return_deadline = None

    deadline_expired = (
        return_deadline is not None and timezone.now() > return_deadline
    )

    month_start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    user_returns = ReturnRequest.objects.filter(user=ret.user)

    user_stats = {
        'total_orders': ret.user.orders.count() if hasattr(ret.user, 'orders') else 0,
        'total_returns': user_returns.count(),
        'returns_this_month': user_returns.filter(created_at__gte=month_start).count(),
        'is_flagged': getattr(ret.user, 'is_flagged', False),
    }

    category = str(ret.order_item.product.category).lower()

    eligibility_checks = [
        {
            'label': 'Order is delivered',
            'passed': ret.order.status == 'delivered',
        },
        {
            'label': f'Within {RETURN_DAYS}-day return window',
            'passed': not deadline_expired,
        },
        {
            'label': 'Product is in returnable category',
            'passed': category not in NON_RETURNABLE,
        },
        {
            'label': 'No previous return for this item',
            'passed': ReturnRequest.objects.filter(
                order_item=ret.order_item,
                status__in=['approved', 'completed']
            ).exclude(pk=ret.pk).count() == 0,
        },
        {
            'label': 'Reason provided',
            'passed': bool(ret.return_reason),
        },
        {
            'label': 'Proof images uploaded',
            'passed': (
                ret.return_reason not in ('defective', 'wrong_item', 'not_as_described')
                or proof_images.exists()
            ),
        },
    ]

    return render(request, 'admin_return_detail.html', {
        'return_request': ret,
        'proof_images': proof_images,
        'internal_notes': internal_notes,
        'return_deadline': return_deadline,
        'deadline_expired': deadline_expired,
        'user_stats': user_stats,
        'eligibility_checks': eligibility_checks,
    })



@never_cache
@login_required(login_url='admin_login')
@require_POST
def admin_return_action(request, pk):
    if not is_admin(request.user):
        return redirect('admin_login')

    ret = get_object_or_404(ReturnRequest, pk=pk)

    action = request.POST.get('action', '').strip()
    reason = request.POST.get('reason', '').strip()

    if action == 'approve':
        ret.status = 'approved'
        ret.save()
        messages.success(request, f'Return #{pk} approved.')

    elif action == 'reject':
        if not reason:
            messages.error(request, 'Please provide a rejection reason.')
            return redirect('admin_return_detail', pk=pk)

        ret.status = 'rejected'
        ret.rejection_reason = reason
        ret.save()
        messages.success(request, f'Return #{pk} rejected.')

    elif action == 'complete':
        ret.status = 'completed'
        ret.save()
        messages.success(request, f'Return #{pk} completed.')

    elif action == 'flag_user':
        user = ret.user
        if hasattr(user, 'is_flagged'):
            user.is_flagged = True
            user.save(update_fields=['is_flagged'])
        messages.warning(request, f'User {user.email} flagged.')

    else:
        messages.error(request, 'Invalid action.')

    return redirect('admin_return_detail', pk=pk)



@never_cache
@login_required(login_url='admin_login')
@require_POST
def admin_return_add_note(request, pk):
    if not is_admin(request.user):
        return redirect('admin_login')

    note_text = request.POST.get('note', '').strip()

    if note_text:
        messages.success(request, 'Note saved.')
    else:
        messages.error(request, 'Note cannot be empty.')

    return redirect('admin_return_detail', pk=pk)