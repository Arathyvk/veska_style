from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Q, Min, Max, Avg

from product_admin.models import Product, ProductReview

PRODUCTS_PER_PAGE = 12
MAX_QTY = 10


SORT_OPTIONS = {
    'newest':     ('Newest First',       '-created_at'),
    'price_asc':  ('Price: Low to High', 'price'),
    'price_desc': ('Price: High to Low', '-price'),
    'name_asc':   ('Name: A–Z',          'name'),
    'name_desc':  ('Name: Z–A',          '-name'),
}

CATEGORY_CHOICES = [
    ('Formal', 'Formal'),
    ('Casual', 'Casual'),
    ('Party',  'Party'),
    ('Sports', 'Sports'),
    ('Ethnic', 'Ethnic'),
    ('Sandal', 'Sandal'),
]

SIZE_CHOICES = [
    ('US 6',  'US 6'),
    ('US 7',  'US 7'),
    ('US 8',  'US 8'),
    ('US 9',  'US 9'),
    ('US 10', 'US 10'),
    ('US 11', 'US 11'),
]


def product_shop(request):
    qs = (
        Product.objects
        .filter(is_active=True)
        .prefetch_related('images', 'variants')
    )

    search_query      = request.GET.get('q', '').strip()
    selected_category = request.GET.get('category', '').strip()
    selected_sizes    = request.GET.getlist('size')  
    price_min_input   = request.GET.get('price_min', '').strip()
    price_max_input   = request.GET.get('price_max', '').strip()
    in_stock_only     = request.GET.get('in_stock', '') == '1'
    sort_key          = request.GET.get('sort', 'newest')
    if sort_key not in SORT_OPTIONS:
        sort_key = 'newest'

    if search_query:
        qs = qs.filter(
            Q(name__icontains=search_query)        |
            Q(description__icontains=search_query) |
            Q(category__icontains=search_query)    |
            Q(color__icontains=search_query)
        )

    if selected_category:
        qs = qs.filter(category=selected_category)

    if selected_sizes:
        qs = qs.filter(
            variants__size__in=selected_sizes,
            variants__stock__gt=0
        ).distinct()

    try:
        if price_min_input:
            qs = qs.filter(price__gte=float(price_min_input))
    except ValueError:
        price_min_input = ''

    try:
        if price_max_input:
            qs = qs.filter(price__lte=float(price_max_input))
    except ValueError:
        price_max_input = ''

    if in_stock_only:
        qs = qs.filter(stock__gt=0)

    _, order_field = SORT_OPTIONS[sort_key]
    qs = qs.order_by(order_field)

    paginator   = Paginator(qs, PRODUCTS_PER_PAGE)
    page_number = request.GET.get('page', 1)
    try:
        page_number = int(page_number)
    except (ValueError, TypeError):
        page_number = 1
    page_obj = paginator.get_page(page_number)

    agg = Product.objects.filter(is_active=True).aggregate(
        mn=Min('price'), mx=Max('price')
    )
    global_price_min = int(agg['mn'] or 0)
    global_price_max = int(agg['mx'] or 10000)

    params = request.GET.copy()
    params.pop('page', None)
    filter_querystring = params.urlencode()  
    has_filters = any([
        search_query,
        selected_category,
        selected_sizes,         
        price_min_input,
        price_max_input,
        in_stock_only,
    ])

    return render(request, 'product_shop.html', {
        'page_obj':           page_obj,
        'products':           page_obj.object_list,
        'paginator':          paginator,
        'total_count':        paginator.count,

        'search_query':       search_query,
        'selected_category':  selected_category,
        'selected_sizes':     selected_sizes,
        'price_min':          price_min_input,
        'price_max':          price_max_input,
        'in_stock_only':      in_stock_only,
        'has_filters':        has_filters,

        'sort_key':           sort_key,
        'sort_options':       SORT_OPTIONS,

        'category_choices':   CATEGORY_CHOICES,
        'size_choices':       SIZE_CHOICES,
        'global_price_min':   global_price_min,
        'global_price_max':   global_price_max,
        'filter_querystring': filter_querystring,
    })

def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)

    images   = list(product.images.all().order_by('order'))
    variants = list(product.variants.all().order_by('size'))

    total_stock = product.total_stock
    if total_stock == 0:
        stock_status = 'out_of_stock'
        stock_label  = 'Out of Stock'
    elif total_stock <= 5:
        stock_status = 'low'
        stock_label  = f'Only {total_stock} left!'
    else:
        stock_status = 'in_stock'
        stock_label  = 'In Stock'

    max_qty = min(total_stock, MAX_QTY)

    original_price   = product.original_price
    discount_percent = product.discount_percent
    savings = (original_price - product.price) if original_price and original_price > product.price else None

    reviews     = product.reviews.filter(is_approved=True).order_by('-created_at')
    review_count = reviews.count()
    avg_data    = reviews.aggregate(avg=Avg('rating'))
    avg_rating  = round(avg_data['avg'] or 0, 1)

   

    related = (
        Product.objects
        .filter(category=product.category, is_active=True)
        .exclude(pk=product.pk)
        .prefetch_related('images')[:4]
    )

    in_cart = False
    if request.user.is_authenticated:
        try:
            from cart_user.models import Cart
            cart = Cart.objects.get(user=request.user)
            in_cart = cart.items.filter(product=product).exists()
        except Exception:
            pass


    category_display = dict(
        [('Formal','Formal'),('Casual','Casual'),('Party','Party'),
         ('Sports','Sports'),('Ethnic','Ethnic'),('Sandal','Sandal')]
    ).get(product.category, product.category)

    highlights = []
    if product.color:
        highlights.append(f'Color: {product.color}')
    if total_stock > 0:
        highlights.append('Free shipping on orders above ₹999')
    highlights.append('Easy 30-day returns')
    highlights.append('Cash on Delivery available')

    size_stock_map = {v.size: v.stock for v in variants}

    return render(request, 'product_detail.html', {
        'product':          product,
        'images':           images,
        'variants':         variants,
        'related':          related,

        'stock_status':     stock_status,
        'stock_label':      stock_label,
        'total_stock':      total_stock,
        'max_qty':          max_qty,

        'original_price':   original_price,
        'discount_percent': discount_percent,
        'savings':          savings,
        'coupon_code':      None,   

        'reviews':          reviews,
        'review_count':     review_count,
        'avg_rating':       avg_rating,

        'in_cart':          in_cart,
        'category_display': category_display,
        'highlights':       highlights,
        'size_stock_map':   size_stock_map,
    })



@require_POST
def submit_review(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)

    rating      = request.POST.get('rating', '').strip()
    body        = request.POST.get('body', '').strip()
    author_name = request.POST.get('author_name', '').strip() or 'Anonymous'

    if not body:
        messages.error(request, 'Please write your review before submitting.')
        return redirect('product_detail', slug=slug)

    try:
        rating_int = int(rating)
        if not (1 <= rating_int <= 5):
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, 'Please select a star rating (1–5).')
        return redirect('product_detail', slug=slug)

    ProductReview.objects.create(
        product     = product,
        author_name = author_name,
        rating      = rating_int,
        body        = body,
        is_approved = False,   
    )

    messages.success(
        request,
        'Thank you! Your review has been submitted and will appear after approval.'
    )
    return redirect('product_detail', slug=slug)


