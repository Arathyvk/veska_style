import json
import base64
import uuid as uuid_lib

from django.shortcuts               import render, redirect, get_object_or_404
from django.contrib                 import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator          import Paginator
from django.core.files.base         import ContentFile
from django.db.models               import Q
from django.views.decorators.cache  import never_cache
from django.http                    import JsonResponse
from django.views.decorators.http   import require_POST

from .models import Product, ProductImage, ProductVariant
from .forms  import ProductForm, ProductVariantForm


def is_admin(user):
    return user.is_authenticated and user.is_staff


def save_cropped_images(product, json_str):
   
    try:
        images = json.loads(json_str or '[]')
    except (json.JSONDecodeError, TypeError):
        return 0

    next_order = product.images.count()
    count = 0
    for i, data_url in enumerate(images):
        if not isinstance(data_url, str) or not data_url.startswith('data:image'):
            continue
        try:
            _header, b64data = data_url.split(',', 1)
            img_bytes = base64.b64decode(b64data)
        except Exception:
            continue
        filename = f"product_{product.uuid}_{uuid_lib.uuid4().hex[:8]}.jpg"
        ProductImage.objects.create(
            product=product,
            image=ContentFile(img_bytes, name=filename),
            order=next_order + i,
        )
        count += 1
    return count


def handle_removed_images(product, json_str):
    try:
        ids = json.loads(json_str or '[]')
    except (json.JSONDecodeError, TypeError):
        return
    for pk in ids:
        try:
            img = ProductImage.objects.get(pk=int(pk), product=product)
            img.image.delete(save=False)
            img.delete()
        except (ProductImage.DoesNotExist, ValueError):
            pass
    for i, img in enumerate(product.images.order_by('order')):
        img.order = i
        img.save(update_fields=['order'])


def save_new_variants(product, json_str):
    try:
        rows = json.loads(json_str or '[]')
    except (json.JSONDecodeError, TypeError):
        return
    for row in rows:
        name = str(row.get('name', '')).strip()
        if not name:
            continue
        ProductVariant.objects.create(
            product=product,
            variant_name=name,
            size=str(row.get('size',  '')).strip(),
            color=str(row.get('color', '')).strip(),
            stock=int(row.get('stock', 0)),
        )


def update_existing_variants(product, post):
    for variant in product.variants.all():
        pk    = variant.pk
        stock = post.get(f'ev_stock_{pk}', '0')
        variant.variant_name = post.get(f'ev_name_{pk}',  '').strip()
        variant.size         = post.get(f'ev_size_{pk}',  '').strip()
        variant.color        = post.get(f'ev_color_{pk}', '').strip()
        variant.stock        = int(stock) if stock.isdigit() else 0
        variant.save()


def delete_variants(product, json_str):
    try:
        ids = json.loads(json_str or '[]')
    except (json.JSONDecodeError, TypeError):
        return
    for pk in ids:
        try:
            ProductVariant.objects.get(pk=int(pk), product=product).delete()
        except (ProductVariant.DoesNotExist, ValueError):
            pass



@never_cache
@login_required(login_url='admin_login')
def product_list(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    query = request.GET.get('q', '').strip()
    sort  = request.GET.get('sort', 'desc')

    qs = Product.objects.prefetch_related('images', 'variants')

    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(category__icontains=query) 
            | Q(color__icontains=query)
        )

    qs = qs.order_by('created_at' if sort == 'asc' else '-created_at')

    paginator = Paginator(qs, 5)
    page      = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'product_list.html', {
        'products': page,
        'query'   : query,
        'sort'    : sort,
    })



@never_cache
@login_required(login_url='admin_login')
def product_add(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    form = ProductForm()

    if request.method == 'POST':
        form = ProductForm(request.POST)

        if form.is_valid():
            is_draft = request.POST.get('save_as_draft') == '1'
            product  = form.save(commit=False)
            if is_draft:
                product.is_active = False
            product.save()

            img_count = save_cropped_images(
                product, request.POST.get('cropped_images_json', '[]')
            )

            if not is_draft and img_count < 3:
                product.delete()
                messages.error(request, 'Minimum 3 product images are required.')
            else:
                save_new_variants(
                    product, request.POST.get('new_variants_json', '[]')
                )
                if is_draft:
                    messages.success(request, f'"{product.name}" saved as draft.')
                else:
                    messages.success(request, f'"{product.name}" added successfully!')
                return redirect('product_list')
        else:
            messages.error(request, 'Please fix the errors below.')

    return render(request, 'product_form.html', {
        'form'        : form,
        'variant_form': ProductVariantForm(),
        'action'      : 'add',
    })



@never_cache
@login_required(login_url='admin_login')
def product_edit(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    product = get_object_or_404(Product, uuid=uuid)
    form    = ProductForm(instance=product)

    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)

        if form.is_valid():
            is_draft = request.POST.get('save_as_draft') == '1'
            product  = form.save(commit=False)
            if is_draft:
                product.is_active = False
            product.save()

            handle_removed_images(
                product, request.POST.get('removed_image_ids', '[]')
            )
            save_cropped_images(
                product, request.POST.get('cropped_images_json', '[]')
            )

            if not is_draft and product.images.count() < 3:
                messages.error(
                    request, 'Product must have at least 3 images. Please add more.'
                )
            else:
                update_existing_variants(product, request.POST)
                delete_variants(
                    product, request.POST.get('deleted_variant_ids', '[]')
                )
                save_new_variants(
                    product, request.POST.get('new_variants_json', '[]')
                )
                if is_draft:
                    messages.success(request, f'"{product.name}" saved as draft.')
                else:
                    messages.success(request, f'"{product.name}" updated successfully!')
                return redirect('product_list')
        else:
            messages.error(request, 'Please fix the errors below.')

    return render(request, 'product_form.html', {
        'form'        : form,
        'variant_form': ProductVariantForm(),
        'product'     : product,
        'action'      : 'edit',
    })



@never_cache
@login_required(login_url='admin_login')
@require_POST
def product_remove(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')
    product = get_object_or_404(Product, uuid=uuid)
    product.is_active = False
    product.save()  
    messages.success(request, f'"{product.name}" has been removed.')
    return redirect('product_list')



@login_required(login_url='admin_login')
@require_POST
def image_delete_ajax(request, pk):
    if not is_admin(request.user):
        return JsonResponse({'ok': False}, status=403)
    try:
        img     = ProductImage.objects.get(pk=pk)
        product = img.product
        img.image.delete(save=False)
        img.delete()
        for i, rem in enumerate(product.images.order_by('order')):
            rem.order = i
            rem.save(update_fields=['order'])
        return JsonResponse({'ok': True, 'remaining': product.images.count()})
    except ProductImage.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)