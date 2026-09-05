import logging
import re
import json
from django.http import Http404, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Q, Min, Max, Avg
from decimal import Decimal, InvalidOperation

from product_admin.models import Product, ProductReview, ProductVariant,ProductImage
from cart_user.models import CartItem
from cart_user.cart_helpers import get_cart, cart_count_payload, wants_json
from wishlist_user.models import Wishlist, WishlistProduct
from category_admin.models import Category

ITEMS_PER_PAGE   = 12
MAX_QTY_PER_ITEM = 10
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
    'price_asc':  'sort_price',
    'price_desc': '-sort_price',
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
    ('Formal', 'Formal')
]
SIZE_CHOICES = ['US 6', 'US 7', 'US 8', 'US 9', 'US 10', 'US 11']

STOCK_CHOICES = [
    ('in_stock',  'In Stock'),
    ('low_stock', 'Low Stock (≤5)'),
    ('out_stock', 'Out of Stock'),
]


logger = logging.getLogger(__name__)

def _get_cart(request):
    return get_cart(request)


def is_valid_email(email):
    return re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email)


def _sanitize_search(raw):
    if not raw:
        return ''
    cleaned = re.sub(r'[^\w\s\-\.\']', ' ', raw)
    return ' '.join(cleaned.split())


def _get_wishlist(request):
    if request.user.is_authenticated:
        wl, _ = Wishlist.objects.get_or_create(user=request.user)
        return wl
    return None


def _wishlist_ids(request):
    if not request.user.is_authenticated:
        return []
    
    try:
        wl = _get_wishlist(request)
        if not wl:
            return []
        
        wishlist_items = wl.items.all()  
        wishlist_ids = [str(item.product.uuid) for item in wishlist_items]
        
        return wishlist_ids
    except Exception as e:
        return []


def product_shop(request):
    qs = (
        Product.objects
        .filter(is_active=True, is_shop_active=True)
        .prefetch_related('variants', 'variants__images')
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
            Q(variants__color__icontains=search_query)
        ).distinct()

    if selected_categories:
        qs = qs.filter(
            category__slug__in=selected_categories
        )

    if selected_sizes:
        qs = qs.filter(
            variants__size__in=selected_sizes,
            variants__stock__gt=0
        ).distinct()

    try:
        price_min = Decimal(price_min_raw) if price_min_raw else None
        if price_min is not None:
            qs = qs.filter(variants__price__gte=price_min)
    except InvalidOperation:
        price_min_raw = ''

    try:
        price_max = Decimal(price_max_raw) if price_max_raw else None
        if price_max is not None:
            qs = qs.filter(variants__price__lte=price_max)
    except ValueError:
        price_max_raw = ''

    if stock_filter == 'in_stock':
        qs = qs.filter(variants__stock__gt=5)

    elif stock_filter == 'low_stock':
        qs = qs.filter(variants__stock__gt=0, variants__stock__lte=5)

    elif stock_filter == 'out_stock':
        qs = qs.filter(variants__stock=0)

    qs = qs.distinct()
    qs = qs.annotate(sort_price=Min("variants__price"))

    sort_field = SORT_MAP.get(sort_key, '-created_at')
    qs = qs.order_by(sort_field)

    paginator = Paginator(qs, ITEMS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page', 1))


    for product in page_obj.object_list:
        best_offer = product.get_best_offer(amount=product.min_price)
        if best_offer:
            setattr(product, 'best_offer', best_offer)
            setattr(product, 'offer_discount', best_offer.calculate_discount(product.min_price))
            setattr(product, 'offer_price', product.min_price - product.offer_discount)
        else:
            setattr(product, 'best_offer', None)
            setattr(product, 'offer_discount', Decimal('0'))
            setattr(product, 'offer_price', product.min_price)
    for product in page_obj:
        product.offer = product.get_best_offer(product.price)
        product.offer_price = product.discounted_price


    current = page_obj.number
    num_pages = paginator.num_pages
    visible = set()
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

    agg = ProductVariant.objects.filter(
        product__is_active=True,
        product__is_shop_active=True
    ).aggregate(
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
        'page_obj': page_obj,
        'total': paginator.count,
        'params_str': params.urlencode(),
        'page_range': page_range,
        'query': search_query,
        'cat_slug_list': selected_categories,
        'size_list': selected_sizes,
        'price_min': price_min_raw,
        'price_max': price_max_raw,
        'stock_filter': stock_filter,
        'has_filters': has_filters,
        'sort_by': sort_key,
        'sort_options': SORT_OPTIONS,
        'all_categories': Category.objects.filter(is_active=True),
        'all_sizes': ProductVariant.SIZE_CHOICES,
        'stock_choices': STOCK_CHOICES,
        'global_price_min': global_price_min,
        'global_price_max': global_price_max,
        'wishlist_ids': _wishlist_ids(request),  
    })


def product_detail(request, slug):
    try:
         product = Product.objects.prefetch_related(
            'variants', 'variants__images', 'reviews'
        ).get(slug=slug)
    except Product.DoesNotExist:
        raise Http404("Product not found.")

    if not product.is_active:
        messages.warning(request, f'"{product.name}" is currently unavailable.')
        return redirect('product_shop')

    images = ProductImage.objects.filter(variant__product=product).order_by("order")
    variants = list(product.variants.all().order_by('size'))

    available_colors = list(
        product.variants
               .exclude(color__isnull=True)
               .exclude(color__exact='')
               .values_list('color', flat=True)
               .distinct()
    )
    available_sizes = list(
        product.variants
               .values_list('size', flat=True)
               .distinct()
               .order_by('size')
    )
    has_color_variants = bool(available_colors)

    size_color_map = {}
    size_stock_map = {}
    for variant in variants:
        color_key = (variant.color or '').strip()
        size_color_map.setdefault(variant.size, []).append(color_key)
        size_stock_map.setdefault(variant.size, 0)
        size_stock_map[variant.size] += variant.stock
    for size, colors in size_color_map.items():
        size_color_map[size] = list(dict.fromkeys(colors))

    size_options = [
        {
            'size': size,
            'colors': size_color_map.get(size, []),
            'stock': size_stock_map.get(size, 0),
        }
        for size in available_sizes
    ]

    variant_gallery = {
        v.id:{
            'size':v.size,
            'color':v.color,
            'price':str(v.price),
            'stock':v.stock,
            'images':[img.image.url for img in v.images.all().order_by('order')],
        }
        for v in variants
    }

    first_variant = product.variants.order_by("price").first()
    product_price = first_variant.price if first_variant else 0
    offer = product.get_best_offer(product_price)
    offer_price = product_price
    if offer:
        offer_price -= offer.calculate_discount(product_price)

    total_stock = product.total_stock
    size_stock_map = {}
    for v in variants:
        size_stock_map.setdefault(v.size, 0)
        size_stock_map[v.size] += v.stock

    if total_stock == 0:
        stock_status, stock_label = 'out_of_stock', 'Out of Stock'
    elif total_stock <= 5:
        stock_status, stock_label = 'low', f'Only {total_stock} left!'
    else:
        stock_status, stock_label = 'in_stock', 'In Stock'

    reviews_qs = ProductReview.objects.filter(product=product)

    for review in reviews_qs:
        print(
            review.id,
            review.product_id,
            review.author_name,
            review.rating,
            review.is_approved
        )    

    reviews_qs = ProductReview.objects.filter(product=product)
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
        (original_price - product_price)
        if (original_price and original_price > product.price)
        else None
    )
    best_offer = product.get_best_offer(amount=product_price)
    offer_discount = best_offer.calculate_discount(product_price) if best_offer else Decimal('0')
    discounted_price = product_price - offer_discount if best_offer else product_price

    savings = (product_price - offer_price) if offer and offer_price < product_price else None
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
        .prefetch_related('variants', 'variants__images')[:6]
    )
    wl          = _get_wishlist(request)
    in_wishlist = (
        wl.items.filter(product_id=product.id).exists()
        if wl else False
    )    
    category_display = product.category.name

    return render(request, 'product_detail.html', {
        'product':          product,
        'images':           images,
        'variants':         variants,
        'available_colors': available_colors,
        'available_sizes':  available_sizes,
        'has_color_variants': has_color_variants,
        'size_options':     size_options,
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
        'product_price':   product_price,
        'best_offer':      best_offer,
        'offer_discount':  offer_discount,
        'discounted_price': discounted_price,
        "product_price": product_price,
        'offer':            offer,
        'offer_price':      offer_price,
        'variant_gallery_json': json.dumps(variant_gallery),
        'size_color_map_json': json.dumps(size_color_map),
        'size_color_map': size_color_map,
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
        user=request.user if request.user.is_authenticated else None,
        product=product,
        author_name=author,
        rating=rating,
        body=body,
        is_approved=True,
    )
    messages.success(request, 'Thank you! Your review has been submitted.')
    return redirect('product_detail', slug=slug)
