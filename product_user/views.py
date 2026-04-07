from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404, JsonResponse
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Avg
from django.views.decorators.http import require_POST
 
from product_admin.models import Product, ProductVariant, ProductReview, CATEGORY_CHOICES
from cart_user.models import Cart, Wishlist, MAX_QTY_PER_ITEM
 
ITEMS_PER_PAGE = 12
 
 

 
def _get_cart(request):
    if not request.session.session_key:
        request.session.create()
    cart, _ = Cart.objects.get_or_create(session_key=request.session.session_key)
    return cart
 
 
def _get_wishlist(request):
    if not request.session.session_key:
        request.session.create()
    wl, _ = Wishlist.objects.get_or_create(session_key=request.session.session_key)
    return wl
 
 

 
def product_shop(request):
    qs = Product.objects.filter(is_active=True).prefetch_related('images', 'variants')
 
    query         = request.GET.get('q', '').strip()
    sort_by       = request.GET.get('sort', 'newest')
    cat_slug_list = request.GET.getlist('category')
    size_list     = request.GET.getlist('size')

    try:
        price_min = float(request.GET.get('price_min', ''))
    except (ValueError, TypeError):
        price_min = None
    try:
        price_max = float(request.GET.get('price_max', ''))
    except (ValueError, TypeError):
        price_max = None
 
    if query:
        qs = qs.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__iexact=query)
        )
    if cat_slug_list:
        qs = qs.filter(category__in=cat_slug_list)

    if size_list:
        qs = qs.filter(
            variants__size__in=size_list,
            variants__stock__gt=0
        ).distinct()
    if price_min is not None:
        qs = qs.filter(price__gte=price_min)
    if price_max is not None:
        qs = qs.filter(price__lte=price_max)
 
    SORT_MAP = {
        'price_asc': 'price', 'price_desc': '-price',
        'name_asc': 'name',   'name_desc': '-name',
        'newest': '-created_at',
    }
    qs = qs.order_by(SORT_MAP.get(sort_by, '-created_at'))
 
    all_categories = [{'slug': val, 'name': label} for val, label in CATEGORY_CHOICES]
    all_sizes      = ['US 6', 'US 7', 'US 8', 'US 9', 'US 10', 'US 11']
 
    paginator = Paginator(qs, ITEMS_PER_PAGE)
    page_obj  = paginator.get_page(request.GET.get('page', 1))
    params    = request.GET.copy()
    params.pop('page', None)
 
    wl           = _get_wishlist(request)
    wishlist_ids = set(wl.products.values_list('id', flat=True))
 
    return render(request, 'product_shop.html', {
        'page_obj':       page_obj,
        'query':          query,
        'sort_by':        sort_by,
        'cat_slug_list':  cat_slug_list,
        'size_list':      size_list,
        'price_min':      price_min,
        'price_max':      price_max,
        'all_sizes':      all_sizes,
        'all_categories': all_categories,
        'total':          paginator.count,
        'params_str':     params.urlencode(),
        'wishlist_ids':   wishlist_ids,
        'cart_count':     _get_cart(request).total_items,
        'sort_options': [
            ('newest',     'Newest First'),
            ('price_asc',  'Price: Low to High'),
            ('price_desc', 'Price: High to Low'),
            ('name_asc',   'Name: A → Z'),
            ('name_desc',  'Name: Z → A'),
        ],
    })
 
 

 
def product_detail(request, slug):
    try:
        product = Product.objects.prefetch_related(
            'images', 'variants', 'reviews'
        ).get(slug=slug)
    except Product.DoesNotExist:
        raise Http404("Product not found.")
 
    if not product.is_active:
        messages.warning(
            request,
            f'"{product.name}" is currently unavailable. Browse our other products below.'
        )
        return redirect('product_shop')
 
    images         = list(product.images.order_by('order'))
    variants       = list(product.variants.all().order_by('size'))
    total_stock    = product.total_stock
    size_stock_map = {v.size: v.stock for v in variants if v.size}
 
    if total_stock == 0:
        stock_status, stock_label = 'out_of_stock', 'Out of Stock'
    elif total_stock <= 5:
        stock_status, stock_label = 'low', f'Only {total_stock} left!'
    else:
        stock_status, stock_label = 'in_stock', 'In Stock'
 
    reviews_qs       = product.reviews.filter(is_approved=True).order_by('-created_at')
    review_count     = reviews_qs.count()
    avg_rating       = 0
    rating_breakdown = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    if review_count:
        avg_rating = round(reviews_qs.aggregate(avg=Avg('rating'))['avg'] or 0, 1)
        for r in reviews_qs:
            rating_breakdown[r.rating] += 1
    reviews = list(reviews_qs[:10])
 
    discount_percent = product.discount_percent
    original_price   = product.original_price
    savings          = product.savings
    coupon_code      = product.coupon_code or None
 
    highlights = product.highlight_list
    if not highlights:
        highlights = [
            'Premium quality materials',
            'Handcrafted with care',
            'Easy returns within 30 days',
            'Free shipping on orders above ₹999',
        ]
 
    related = (
        Product.objects
        .filter(is_active=True, category=product.category)
        .exclude(pk=product.pk)
        .prefetch_related('images')[:6]
    )
 
    wl          = _get_wishlist(request)
    in_wishlist = wl.products.filter(pk=product.pk).exists()
 
    category_display = dict(CATEGORY_CHOICES).get(product.category, product.category)
 
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
        'discount_percent': discount_percent,
        'original_price':   original_price,
        'savings':          savings,
        'coupon_code':      coupon_code,
        'highlights':       highlights,
        'category_display': category_display,
        'in_wishlist':      in_wishlist,
        'cart_count':       _get_cart(request).total_items,
    })
 

def shop(request):
    category = request.GET.get('category')
    
    if category:
        products = Product.objects.filter(category=category)
    else:
        products = Product.objects.all()

    return render(request, 'shop.html', {'products': products})