import re
from django.http import Http404, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Q, Min, Max, Avg

from product_admin.models import Product, ProductReview, ProductVariant
from cart_user.models import Cart, CartItem
from cart_user.cart_helpers import get_cart, cart_count_payload, wants_json
from wishlist_user.models import Wishlist

ITEMS_PER_PAGE   = 12
MAX_QTY_PER_ITEM = 10
FREE_SHIPPING    = 999
SHIPPING_FEE     = 79

SORT_OPTIONS = [
    ('newest',     'Newest First'),
    ('price_asc',  'Price: Low to High'),
    ('price_desc', 'Price: High to Low'),
    ('name_asc',   'Name: A → Z'),
    ('name_desc',  'Name: Z → A'),
]
SORT_MAP = {
    'newest':     '-created_at',
    'price_asc':  'price',
    'price_desc': '-price',
    'name_asc':   'name',
    'name_desc':  '-name',
}

CATEGORY_CHOICES = [
    ('Sneakers', 'Sneakers'),
    ('Heels', 'Heels'),
    ('Flats', 'Flats'),
    ('Boots', 'Boots'),
    ('Sandals', 'Sandals'),
    ('Loafers', 'Loafers'),
    ('Sports Shoes', 'Sports Shoes'),
    ('Casual', 'Casual'),
]
SIZE_CHOICES = ['US 6', 'US 7', 'US 8', 'US 9', 'US 10', 'US 11']

STOCK_CHOICES = [
    ('in_stock',  'In Stock'),
    ('low_stock', 'Low Stock (≤5)'),
    ('out_stock', 'Out of Stock'),
]


def _sanitize_search(raw: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z\u0900-\u097F\s']", '', raw)
    return ' '.join(cleaned.split())


def _get_cart(request):
    return get_cart(request)


def _get_wishlist(request):
    if not request.user.is_authenticated:
        return None
    wl, _ = Wishlist.objects.get_or_create(user=request.user)
    return wl


def _wishlist_ids(request):
    wl = _get_wishlist(request)
    if wl is None:
        return set()
    return set(wl.products.values_list('id', flat=True))



def product_shop(request):

    qs = (
        Product.objects
        .filter(is_active=True, is_shop_active=True)
        .prefetch_related('images', 'variants')
    )

    raw_query = request.GET.get('q', '').strip()
    search_query = _sanitize_search(raw_query)

    selected_categories = request.GET.getlist('category')
    selected_sizes = request.GET.getlist('size')

    price_min_raw = request.GET.get('price_min', '').strip()
    price_max_raw = request.GET.get('price_max', '').strip()

    stock_filter = request.GET.get('stock', '').strip()

    sort_key = request.GET.get('sort', 'newest')
    if sort_key not in SORT_MAP:
        sort_key = 'newest'

    if search_query:
        qs = qs.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query) |
            Q(color__icontains=search_query)
        )

    if selected_categories:
        qs = qs.filter(
            category__name__in=selected_categories
        )

    if selected_sizes:
        qs = qs.filter(
            variants__size__in=selected_sizes,
            variants__stock__gt=0
        ).distinct()

    try:
        price_min = float(price_min_raw) if price_min_raw else None
        if price_min is not None:
            qs = qs.filter(price__gte=price_min)
    except ValueError:
        price_min_raw = ''

    try:
        price_max = float(price_max_raw) if price_max_raw else None
        if price_max is not None:
            qs = qs.filter(price__lte=price_max)
    except ValueError:
        price_max_raw = ''

    if stock_filter == 'in_stock':
        qs = qs.filter(variants__stock__gt=5)

    elif stock_filter == 'low_stock':
        qs = qs.filter(variants__stock__gt=0, variants__stock__lte=5)

    elif stock_filter == 'out_stock':
        qs = qs.filter(variants__stock=0)

    qs = qs.distinct()

    sort_field = SORT_MAP.get(sort_key, '-created_at')         
    qs = qs.order_by(sort_field)

    paginator = Paginator(qs, ITEMS_PER_PAGE)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

  
    current   = page_obj.number
    num_pages = paginator.num_pages
    visible   = set()
    visible.add(1)
    visible.add(num_pages)
    for i in range(max(1, current - 2), min(num_pages, current + 2) + 1):
        visible.add(i)

    page_range = []
    prev_p = None
    for p in sorted(visible):
        if prev_p is not None and p - prev_p > 1:
            page_range.append(None)   
        page_range.append(p)
        prev_p = p

    agg = Product.objects.filter(is_active=True, is_shop_active=True).aggregate(
        mn=Min('price'), mx=Max('price')
    )
    global_price_min = int(agg['mn'] or 0)
    global_price_max = int(agg['mx'] or 10000)

    params = request.GET.copy()
    params.pop('page', None)

    has_filters = any([
        search_query, selected_categories, selected_sizes,
        price_min_raw, price_max_raw, stock_filter,
    ])

    return render(request, 'product_shop.html', {
        'page_obj':            page_obj,
        'total':               paginator.count,
        'params_str':          params.urlencode(),
        'page_range':          page_range,         

        'query':               search_query,

        'cat_slug_list':       selected_categories,
        'size_list':           selected_sizes,
        'price_min':           price_min_raw,
        'price_max':           price_max_raw,
        'stock_filter':        stock_filter,
        'has_filters':         has_filters,

        'sort_by':             sort_key,
        'sort_options':        SORT_OPTIONS,

        'all_categories':      CATEGORY_CHOICES,   
        'all_sizes':           SIZE_CHOICES,        
        'stock_choices':       STOCK_CHOICES,       

        'global_price_min':    global_price_min,
        'global_price_max':    global_price_max,

        'wishlist_ids':        _wishlist_ids(request),
    })


def product_detail(request, slug):
    try:
         product = Product.objects.prefetch_related(
            'images', 'variants', 'reviews'
        ).get(slug=slug)
    except Product.DoesNotExist:
        raise Http404("Product not found.")

    if not product.is_active:
        messages.warning(request, f'"{product.name}" is currently unavailable.')
        return redirect('product_shop')

    images         = list(product.images.order_by('order'))
    variants       = list(product.variants.all().order_by('size'))
    total_stock    = product.total_stock
    size_stock_map = {v.size: v.stock for v in variants}

    if total_stock == 0:
        stock_status, stock_label = 'out_of_stock', 'Out of Stock'
    elif total_stock <= 5:
        stock_status, stock_label = 'low', f'Only {total_stock} left!'
    else:
        stock_status, stock_label = 'in_stock', 'In Stock'

    print("Current Product:", product.id, product.name)

    reviews_qs = ProductReview.objects.filter(product=product)

    print("Review Count:", reviews_qs.count())

    for review in reviews_qs:
        print(
            review.id,
            review.product_id,
            review.author_name,
            review.rating,
            review.is_approved
        )    
    review_count     = reviews_qs.count()
    avg_rating       = 0
    rating_breakdown = [0, 0, 0, 0, 0]
    if review_count:
        avg_rating = round(reviews_qs.aggregate(avg=Avg('rating'))['avg'] or 0, 1)
        for r in reviews_qs:
            if 1 <= r.rating <= 5:
                rating_breakdown[5 - r.rating] += 1
    reviews = list(reviews_qs[:10])

    original_price   = getattr(product, 'original_price', None)
    discount_percent = getattr(product, 'discount_percent', 0)
    savings = (
        (original_price - product.price)
        if (original_price and original_price > product.price)
        else None
    )
    highlights = getattr(product, 'highlight_list', None) or [
        'Premium quality materials',
        'Handcrafted with care',
        'Easy 30-day returns',
        'Free shipping above ₹999',
    ]
    related = (
        Product.objects
        .filter(is_active=True, category=product.category)
        .exclude(pk=product.pk)
        .prefetch_related('images')[:6]
    )
    wl          = _get_wishlist(request)
    in_wishlist = wl.products.filter(pk=product.pk).exists() if wl else False
    category_display = product.category.name

    return render(request, 'product_detail.html', {
        'product':          product,
        'images':           images,
        'variants':         variants,
        'size_stock_map':   size_stock_map,
        'total_stock':      total_stock,
        'stock_status':     stock_status,
        'stock_label':      stock_label,
        'max_qty':          min(total_stock, MAX_QTY_PER_ITEM) if total_stock else 0,
        'related':          related,
        'reviews':          reviews,
        'avg_rating':       avg_rating,
        'review_count':     review_count,
        'rating_breakdown': rating_breakdown,
        'original_price':   original_price,
        'discount_percent': discount_percent,
        'savings':          savings,
        'highlights':       highlights,
        'in_wishlist':      in_wishlist,
        'category_display': category_display,
    })


@require_POST
def cart_add_with_size(request):
    product_id = request.POST.get('product_id')
    size = request.POST.get('size')
    quantity = int(request.POST.get('quantity', 1))
    next_url = request.POST.get('next', '/shop/')
    
    if not product_id or not size:
        messages.error(request, 'Please select a size')
        return redirect(next_url)
    
    try:
        product = Product.objects.get(id=product_id, is_active=True)
    except Product.DoesNotExist:
        messages.error(request, 'Product not found')
        return redirect(next_url)
    
    try:
        variant = ProductVariant.objects.get(product=product, size=size)
    except ProductVariant.DoesNotExist:
        messages.error(request, f'Size {size} is not available for this product')
        return redirect(next_url)
    
    if variant.stock < quantity:
        messages.error(request, f'Only {variant.stock} units available in size {size}')
        return redirect(next_url)
    
    cart = _get_cart(request)
    
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        variant=variant,
        defaults={'quantity': quantity}
    )
    
    if not created:
        cart_item.quantity += quantity
        if cart_item.quantity > variant.stock:
            cart_item.quantity = variant.stock
        cart_item.save()
    
    msg = f'{product.name} (Size: {size}) added to cart'
    if wants_json(request):
        payload = cart_count_payload(request, cart)
        payload['message'] = msg
        return JsonResponse(payload)
    messages.success(request, msg)
    return redirect(next_url)


@require_POST
def submit_review(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    try:
        rating = int(request.POST.get('rating', 0))
        body   = request.POST.get('body', '').strip()
        author = request.POST.get('author_name', '').strip() or 'Anonymous'
        if rating < 1 or rating > 5:
            raise ValueError
        if not body:
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, 'Please provide a rating (1–5) and review text.')
        return redirect('product_detail', slug=slug)
    ProductReview.objects.create(
        product=product, author_name=author,
        rating=rating, body=body, is_approved=True,
    )
    messages.success(request, 'Thank you! Your review has been submitted.')
    return redirect('product_detail', slug=slug)