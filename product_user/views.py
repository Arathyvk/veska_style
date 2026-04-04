from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q, Avg, Count

from product_admin.models import Product, ProductVariant, CATEGORY_CHOICES

ITEMS_PER_PAGE = 12


def product_shop(request):
    qs = Product.objects.filter(is_active=True).prefetch_related('images', 'variants')

    query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', 'newest')
    cat_slug = request.GET.get('category', '').strip()
    size_selected = request.GET.get('size') or None

    try:
        price_min = float(request.GET.get('price_min', ''))
    except:
        price_min = None

    try:
        price_max = float(request.GET.get('price_max', ''))
    except:
        price_max = None

    if query:
        qs = qs.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__iexact=query)
        )

    if cat_slug:
        qs = qs.filter(category=cat_slug)

    if size_selected:
        qs = qs.filter(
            variants__size=size_selected,
            variants__stock__gt=0
        ).distinct()

    if price_min is not None:
        qs = qs.filter(price__gte=price_min)

    if price_max is not None:
        qs = qs.filter(price__lte=price_max)

    SORT_MAP = {
        'price_asc': 'price',
        'price_desc': '-price',
        'name_asc': 'name',
        'name_desc': '-name',
        'newest': '-created_at',
    }
    qs = qs.order_by(SORT_MAP.get(sort_by, '-created_at'))

    all_categories = [{'slug': val, 'name': label} for val, label in CATEGORY_CHOICES]

    all_sizes = ProductVariant.objects.filter(
        product__in=qs,
        stock__gt=0
    ).exclude(size="").values_list('size', flat=True).distinct()

    all_sizes = ['US 6', 'US 7', 'US 8', 'US 9', 'US 10', 'US 11']

    paginator = Paginator(qs, ITEMS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'product_shop.html', {
        'page_obj': page_obj,
        'query': query,
        'sort_by': sort_by,
        'cat_slug': cat_slug,
        'size_selected': size_selected,
        'price_min': price_min,
        'price_max': price_max,
        'all_sizes': all_sizes,
        'all_categories': all_categories,
        'total': paginator.count,
        'params_str': params.urlencode(),
        'sort_options': [
            ('newest', 'Newest First'),
            ('price_asc', 'Price: Low to High'),
            ('price_desc', 'Price: High to Low'),
            ('name_asc', 'Name: A → Z'),
            ('name_desc', 'Name: Z → A'),
        ],
    })


def product_detail(request, slug):
    try:
        product = Product.objects.prefetch_related(
            'images', 'variants', 'reviews'
        ).get(slug=slug)
    except Product.DoesNotExist:
        from django.http import Http404
        raise Http404("Product not found.")

    if not product.is_active:
        from django.contrib import messages
        messages.warning(
            request,
            f"\"{product.name}\" is currently unavailable. Browse our other products below."
        )
        return redirect('product_shop')

    images = list(product.images.order_by('order'))

    variants = list(product.variants.all().order_by('size'))
    total_stock = product.total_stock 
    size_stock_map = {v.size: v.stock for v in variants if v.size}

    if total_stock == 0:
        stock_status = 'out_of_stock'
        stock_label = 'Out of Stock'
    elif total_stock <= 5:
        stock_status = 'low'
        stock_label = f'Only {total_stock} left!'
    else:
        stock_status = 'in_stock'
        stock_label = 'In Stock'

    reviews = []
    avg_rating = 0
    review_count = 0
    rating_breakdown = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    try:
        reviews_qs = product.reviews.filter(is_approved=True).order_by('-created_at')
        review_count = reviews_qs.count()
        if review_count:
            agg = reviews_qs.aggregate(avg=Avg('rating'))
            avg_rating = round(agg['avg'] or 0, 1)
            for r in reviews_qs:
                rating_breakdown[r.rating] = rating_breakdown.get(r.rating, 0) + 1
        reviews = list(reviews_qs[:10])
    except Exception:
        pass

    discount_percent = 0
    original_price = None
    savings = 0
    try:
        if hasattr(product, 'original_price') and product.original_price and product.original_price > product.price:
            original_price = product.original_price
            savings = original_price - product.price
            discount_percent = round((savings / original_price) * 100)
    except Exception:
        pass

    coupon_code = getattr(product, 'coupon_code', None)

    related = Product.objects.filter(
        is_active=True,
        category=product.category
    ).exclude(pk=product.pk).prefetch_related('images')[:6]

    highlights = []
    try:
        raw = getattr(product, 'highlights', None)
        if raw:
            if isinstance(raw, list):
                highlights = raw
            elif isinstance(raw, str):
                highlights = [h.strip() for h in raw.splitlines() if h.strip()]
    except Exception:
        pass

    if not highlights:
        highlights = [
            'Premium quality materials',
            'Handcrafted with care',
            'Easy returns within 30 days',
            'Free shipping on orders above ₹999',
        ]

    category_display = dict(CATEGORY_CHOICES).get(product.category, product.category)

    return render(request, 'product_detail.html', {
        'product': product,
        'images': images,
        'variants': variants,
        'size_stock_map': size_stock_map,
        'total_stock': total_stock,
        'stock_status': stock_status,
        'stock_label': stock_label,
        'max_qty': min(total_stock, 10),
        'related': related,
        'reviews': reviews,
        'avg_rating': avg_rating,
        'review_count': review_count,
        'rating_breakdown': rating_breakdown,
        'discount_percent': discount_percent,
        'original_price': original_price,
        'savings': savings,
        'coupon_code': coupon_code,
        'highlights': highlights,
        'category_display': category_display,
    })