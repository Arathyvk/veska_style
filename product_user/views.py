from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Q, Min, Max

from product_admin.models import Product
from category_admin.models import Category


PRODUCTS_PER_PAGE = 12

SORT_OPTIONS = {
    'price_asc':  ('Price: Low to High', 'price'),
    'price_desc': ('Price: High to Low', '-price'),
    'name_asc':   ('Name: A–Z',          'name'),
    'name_desc':  ('Name: Z–A',          '-name'),
    'newest':     ('Newest First',       '-created_at'),
}


# ─────────────────────────────────────────────
#  SHOP / PRODUCT LISTING
# ─────────────────────────────────────────────

def product_shop(request):
    # ── Base queryset: only visible products ──
    qs = Product.objects.filter(
        is_listed=True,
        is_blocked=False,
        category__is_listed=True,
    ).select_related('category', 'brand').prefetch_related('images')

    # ── 1. Search ──────────────────────────────
    search_query = request.GET.get('q', '').strip()
    if search_query:
        qs = qs.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query) |
            Q(brand__name__icontains=search_query)
        )

    # ── 2. Category filter ─────────────────────
    category_slug = request.GET.get('category', '').strip()
    selected_category = None
    if category_slug:
        selected_category = Category.objects.filter(slug=category_slug, is_listed=True).first()
        if selected_category:
            qs = qs.filter(category=selected_category)

    # ── 3. Brand filter ────────────────────────
    brand_slug = request.GET.get('brand', '').strip()
    selected_brand = None
    if brand_slug:
        selected_brand = Brand.objects.filter(slug=brand_slug, is_listed=True).first()
        if selected_brand:
            qs = qs.filter(brand=selected_brand)

    # ── 4. Price range filter ──────────────────
    price_min_input = request.GET.get('price_min', '').strip()
    price_max_input = request.GET.get('price_max', '').strip()
    price_min = None
    price_max = None
    try:
        if price_min_input:
            price_min = float(price_min_input)
            qs = qs.filter(price__gte=price_min)
    except ValueError:
        price_min = None
    try:
        if price_max_input:
            price_max = float(price_max_input)
            qs = qs.filter(price__lte=price_max)
    except ValueError:
        price_max = None

    # ── 5. Stock filter ────────────────────────
    in_stock_only = request.GET.get('in_stock', '') == '1'
    if in_stock_only:
        qs = qs.filter(stock__gt=0)

    # ── 6. Sort ────────────────────────────────
    sort_key = request.GET.get('sort', 'newest')
    if sort_key not in SORT_OPTIONS:
        sort_key = 'newest'
    _, order_field = SORT_OPTIONS[sort_key]
    qs = qs.order_by(order_field)

    # ── 7. Pagination ──────────────────────────
    paginator   = Paginator(qs, PRODUCTS_PER_PAGE)
    page_number = request.GET.get('page', 1)
    try:
        page_number = int(page_number)
    except (ValueError, TypeError):
        page_number = 1
    page_obj = paginator.get_page(page_number)

    # ── Sidebar data ────────────────────────────
    all_categories = Category.objects.filter(is_listed=True).order_by('name')
    all_brands     = Brand.objects.filter(is_listed=True).order_by('name')

    # Overall price range for the slider (unfiltered)
    price_range = Product.objects.filter(
        is_listed=True, is_blocked=False
    ).aggregate(min=Min('price'), max=Max('price'))
    global_price_min = int(price_range['min'] or 0)
    global_price_max = int(price_range['max'] or 10000)

    # Build query string without 'page' so paginator links preserve other params
    get_params = request.GET.copy()
    get_params.pop('page', None)
    filter_querystring = get_params.urlencode()

    # Check if any filter is active (for "clear filters" button)
    has_filters = any([
        search_query, category_slug, brand_slug,
        price_min_input, price_max_input, in_stock_only,
    ])

    return render(request, 'product_shop.html', {
        'page_obj':          page_obj,
        'products':          page_obj.object_list,
        'paginator':         paginator,

        # search / filters
        'search_query':      search_query,
        'selected_category': selected_category,
        'selected_brand':    selected_brand,
        'price_min':         price_min_input,
        'price_max':         price_max_input,
        'in_stock_only':     in_stock_only,
        'has_filters':       has_filters,

        # sort
        'sort_key':          sort_key,
        'sort_options':      SORT_OPTIONS,

        # sidebar
        'all_categories':    all_categories,
        'all_brands':        all_brands,
        'global_price_min':  global_price_min,
        'global_price_max':  global_price_max,

        # pagination query string (preserves all GET params except page)
        'filter_querystring': filter_querystring,

        'total_count': paginator.count,
    })


# ─────────────────────────────────────────────
#  PRODUCT DETAIL
# ─────────────────────────────────────────────

def product_detail(request, slug):
    product = get_object_or_404(
        Product,
        slug=slug,
        is_listed=True,
        is_blocked=False,
    )
    variants       = product.variants.all()
    related        = Product.objects.filter(
                         category=product.category,
                         is_listed=True,
                         is_blocked=False,
                     ).exclude(pk=product.pk)[:4]

    # Check if in cart (for logged-in users)
    in_cart = False
    if request.user.is_authenticated:
        try:
            from cart_user.models import Cart
            cart = Cart.objects.get(user=request.user)
            in_cart = cart.items.filter(product=product).exists()
        except Exception:
            pass

    return render(request, 'product_detail.html', {
        'product':  product,
        'variants': variants,
        'related':  related,
        'in_cart':  in_cart,
    })