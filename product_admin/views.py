from django.shortcuts import render

import json, base64, uuid as uuid_lib
 
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.files.base import ContentFile
from django.db.models import Q
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
 
from .models import Product, ProductImage
from .forms import ProductForm, ProductVariantForm

 
def is_admin(user):
    return user.is_authenticated and user.is_staff
 
 
def save_cropped_images(product, json_str):
    try:
        images = json.loads(json_str or '[]')
    except (json.JSONDecodeError, TypeError):
        return 0
    count = 0
    for i, data_url in enumerate(images):
        if not data_url.startswith('data:image'):
            continue
        header, b64data = data_url.split(',', 1)
        img_bytes = base64.b64decode(b64data)
        filename  = f"product_{product.pk}_{uuid_lib.uuid4().hex[:8]}.jpg"
        ProductImage.objects.create(
            product=product,
            image=ContentFile(img_bytes, name=filename),
            order=i,
        )
        count += 1
    return count


@never_cache
@login_required(login_url='admin_login')
def product_list(request):
    if not is_admin(request.user):
        return redirect('admin_login')
    query    = request.GET.get('q', '').strip()
    sort     = request.GET.get('sort', 'desc')
    products = Product.objects.prefetch_related('images')
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(category__icontains=query) | Q(color__icontains=query)
        )
    products  = products.order_by('created_at' if sort == 'asc' else '-created_at')
    paginator = Paginator(products, 5)
    page      = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'product_list.html', {'products': page, 'query': query, 'sort': sort})
 
 
@never_cache
@login_required(login_url='admin_login')
def product_add(request):
    if not is_admin(request.user):
        return redirect('admin_login')
    form = ProductForm()
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            product   = form.save()
            img_count = save_cropped_images(product, request.POST.get('cropped_images_json', '[]'))
            if img_count < 3:
                product.delete()
                messages.error(request, 'Minimum 3 product images are required.')
            else:
                messages.success(request, f'"{product.name}" added successfully!')
                return redirect('product_list')
        else:
            messages.error(request, 'Please fix the errors below.')
    return render(request, 'product_form.html', {
        'form': form, 'variant_form': ProductVariantForm(), 'action': 'add'
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
            product   = form.save()
            new_count = save_cropped_images(product, request.POST.get('cropped_images_json', '[]'))
            if new_count > 0 and new_count < 3:
                messages.error(request, 'If uploading new images, minimum 3 are required.')
            else:
                messages.success(request, f'"{product.name}" updated successfully!')
                return redirect('product_list')
        else:
            messages.error(request, 'Please fix the errors below.')
    return render(request, 'product_form.html', {
        'form': form, 'variant_form': ProductVariantForm(),
        'product': product, 'action': 'edit'
    })


def product_create(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        image_form = ProductImageUploadForm(request.POST, request.FILES)

        if form.is_valid() and image_form.is_valid():
            product = form.save()

            images = request.FILES.getlist('images')  

            for index, img in enumerate(images):
                ProductImage.objects.create(
                    product=product,
                    image=img,
                    order=index
                )

            return redirect('product_list')