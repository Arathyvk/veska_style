import uuid as _uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Sum, F
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.urls import reverse

from offer_admin.models import BaseOffer, UserOfferUsage
from users.models import ReferralCode, ReferralTransaction
from .forms import BaseOfferForm, ReferralOfferForm
from product_admin.models import Product
from category_admin.models import Category


def is_admin(user):
    return user.is_authenticated and user.is_staff


@never_cache
@login_required(login_url='admin_login')
def offer_list(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    query      = request.GET.get('q', '').strip()
    offer_type = request.GET.get('type', '')
    status     = request.GET.get('status', '')

    offers = BaseOffer.objects.all()

    if query:
        offers = offers.filter(
            Q(name__icontains=query) | Q(referral_code__icontains=query)
        )

    if offer_type:
        offers = offers.filter(offer_type=offer_type)

    now = timezone.now()
    if status == 'active':
        offers = offers.filter(is_active=True, start_date__lte=now, end_date__gte=now)
    elif status == 'expired':
        offers = offers.filter(end_date__lt=now)
    elif status == 'inactive':
        offers = offers.filter(is_active=False)

    offers = offers.order_by('-created_at')

    paginator = Paginator(offers, 10)
    page      = request.GET.get('page')

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return render(request, 'offer_list.html', {
        'offers':     page_obj,
        'query':      query,
        'offer_type': offer_type,
        'status':     status,
    })


@never_cache
@login_required(login_url='admin_login')
def offer_add(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    if request.method == 'POST':
        form = BaseOfferForm(request.POST)
        if form.is_valid():
            offer = form.save()
            messages.success(request, f'Offer "{offer.name}" created successfully!')
            return redirect('offer_list')
        messages.error(request, 'Please fix the errors below.')
    else:
        form = BaseOfferForm(initial={
            'start_date': timezone.now(),
            'end_date':   timezone.now() + timezone.timedelta(days=30),
        })

    return render(request, 'offer_form.html', {
        'form':       form,
        'action':     'add',
        'products':   Product.objects.filter(is_active=True),
        'categories': Category.objects.all(),
    })


@never_cache
@login_required(login_url='admin_login')
def referral_offer_add(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    if request.method == 'POST':
        form = ReferralOfferForm(request.POST)
        if form.is_valid():
            offer = form.save(commit=False)
            offer.offer_type = 'REFERRAL'
            if not offer.referral_code:
                offer.referral_code = f"REF{_uuid.uuid4().hex[:8].upper()}"
            offer.save()
            messages.success(request, f'Referral offer "{offer.name}" created!')
            return redirect('offer_edit', uuid=offer.uuid)
    else:
        form = ReferralOfferForm(initial={
            'start_date':              timezone.now(),
            'end_date':                timezone.now() + timezone.timedelta(days=30),
            'discount_type':           'PERCENTAGE',
            'discount_value':          10,
            'referral_reward_amount':  100,
            'referred_user_reward':    50,
        })

    return render(request, 'referral_offer_form.html', {'form': form, 'action': 'add'})


@never_cache
@login_required(login_url='admin_login')
def offer_edit(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    offer = get_object_or_404(BaseOffer, uuid=uuid)
    is_referral = offer.offer_type == 'REFERRAL'
    FormClass = ReferralOfferForm if is_referral else BaseOfferForm
    template = 'referral_offer_form.html' if is_referral else 'offer_form.html'

    if request.method == 'POST':
        form = FormClass(request.POST, instance=offer)
        if form.is_valid():
            form.save()
            messages.success(request, f'Offer "{offer.name}" updated!')
            return redirect('offer_list')
        messages.error(request, 'Please fix the errors below.')
    else:
        form = FormClass(instance=offer)

    context = {'form': form, 'offer': offer, 'action': 'edit'}

    if is_referral:
        signup_path = reverse('signup')
        context['referral_link'] = request.build_absolute_uri(f'{signup_path}?ref={offer.referral_code}')
    else:
        context.update({
            'products':   Product.objects.filter(is_active=True),
            'categories': Category.objects.all(),
        })

    return render(request, template, context)  


@never_cache
@login_required(login_url='admin_login')
@require_POST
def offer_toggle_status(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    offer           = get_object_or_404(BaseOffer, uuid=uuid)
    offer.is_active = not offer.is_active
    offer.save()
    verb = 'activated' if offer.is_active else 'deactivated'
    messages.success(request, f'Offer "{offer.name}" {verb}.')
    return redirect('offer_list')


@never_cache
@login_required(login_url='admin_login')
@require_POST
def offer_delete(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    offer = get_object_or_404(BaseOffer, uuid=uuid)
    name  = offer.name
    offer.delete()
    messages.success(request, f'Offer "{name}" deleted.')
    return redirect('offer_list')


@never_cache
@login_required(login_url='admin_login')
def referral_stats(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    total_referrals    = ReferralTransaction.objects.count()
    total_earnings = (
        ReferralTransaction.objects
        .filter(is_credited=True)
        .aggregate(total=Sum(F('amount_earned') + F('referred_user_bonus')))['total'] or 0
    )
    active_codes        = ReferralCode.objects.filter(is_active=True).count()
    recent_transactions = (
        ReferralTransaction.objects
        .select_related('referrer', 'referred_user')
        .order_by('-created_at')[:20]
    )
    top_referrers      = ReferralCode.objects.filter(is_active=True).order_by('-total_referrals')[:10]

    return render(request, 'referral_stats.html', {
        'total_referrals':    total_referrals,
        'total_earnings':     total_earnings,
        'active_codes':       active_codes,
        'recent_transactions': recent_transactions,
        'top_referrers':      top_referrers,
    })


def get_applicable_offers(product, user=None):
    now = timezone.now()

    product_offers  = BaseOffer.objects.filter(
        offer_type='PRODUCT', products=product,
        is_active=True, start_date__lte=now, end_date__gte=now,
    )
    category_offers = BaseOffer.objects.filter(
        offer_type='CATEGORY', categories=product.category,
        is_active=True, start_date__lte=now, end_date__gte=now,
    )
    offers = list(product_offers) + list(category_offers)

    if user and user.is_authenticated:
        valid = []
        for offer in offers:
            usage, _ = UserOfferUsage.objects.get_or_create(user=user, offer=offer)
            within_global_limit = (offer.usage_limit == 0 or offer.used_count < offer.usage_limit)
            if usage.can_use() and within_global_limit:
                valid.append(offer)
        return valid

    return offers