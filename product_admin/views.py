import json
import base64
import uuid as uuid_lib
import os

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.files.base import ContentFile
from django.db.models import Q
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from product_admin.models import Product, ProductImage
from product_admin.forms import ProductForm, ProductVariantFormSet
from category_admin.models import Category


def is_admin(user):
    return user.is_authenticated and user.is_staff


def count_product_images(product):
    count = 0
    for variant in product.variants.all():
        count += variant.images.count()
    return count


def _parse_json(data, default):
    try:
        parsed = json.loads(data or default)
        return parsed if isinstance(parsed, list) else default
    except (json.JSONDecodeError, TypeError):
        return default


def save_cropped_images(variant, json_str):
    if not variant:
        return 0
    
    images = _parse_json(json_str, [])
    if not images:
        return 0
    
    next_order = variant.images.count()
    count = 0
    
    for i, data_url in enumerate(images):
        if not isinstance(data_url, str) or not data_url.startswith('data:image'):
            continue
        try:
            _, b64data = data_url.split(',', 1)
            img_bytes = base64.b64decode(b64data)
        except Exception as e:
            continue
            
        filename = f"product_{variant.product.uuid}_{uuid_lib.uuid4().hex[:8]}.jpg"
        try:
            ProductImage.objects.create(
                variant=variant,
                image=ContentFile(img_bytes, name=filename),
                order=next_order + count,
            )
            count += 1
        except Exception as e:
            continue
            
    return count


def handle_removed_images(product, json_str):
    ids = _parse_json(json_str, [])
    if not ids:
        return
    
    deleted_count = 0
    for pk in ids:
        try:
            img = ProductImage.objects.get(pk=int(pk), variant__product=product)
            
            if img.image:
                if os.path.isfile(img.image.path):
                    os.remove(img.image.path)
                img.image.delete(save=False)
            
            img.delete()
            deleted_count += 1
            
        except ProductImage.DoesNotExist:
            continue
        except ValueError as e:
            continue
        except Exception as e:
            continue
    
    for variant in product.variants.all():
        for i, img in enumerate(variant.images.order_by('order')):
            if img.order != i:
                img.order = i
                img.save(update_fields=['order'])
    
    return deleted_count


def delete_unused_variant_images(product):
    existing_variant_ids = list(product.variants.values_list('id', flat=True))
    
    unused_images = ProductImage.objects.filter(
        variant__product=product
    ).exclude(
        variant_id__in=existing_variant_ids
    )
    
    deleted_count = 0
    for img in unused_images:
        try:
            if img.image:
                if os.path.isfile(img.image.path):
                    os.remove(img.image.path)
                img.image.delete(save=False)
            img.delete()
            deleted_count += 1
        except Exception as e:
            continue
    return deleted_count


@never_cache
@login_required(login_url='admin_login')
def product_list(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    query = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', 'desc')

    qs = Product.objects.prefetch_related('variants__images', 'variants')

    if query:
        qs = qs.filter(
            Q(name__icontains=query) |
            Q(category__name__icontains=query) |
            Q(brand__icontains=query) |
            Q(variants__color__icontains=query)
        ).distinct()

    qs = qs.order_by('created_at' if sort == 'asc' else '-created_at')

    paginator = Paginator(qs, 5)
    page = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'product_list.html', {
        'products': page,
        'query': query,
        'sort': sort,
    })


@never_cache
@login_required(login_url='admin_login')
def product_add(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    if request.method == 'POST':
        form = ProductForm(request.POST)
        variant_formset = ProductVariantFormSet(request.POST, prefix='variants')

        if form.is_valid() and variant_formset.is_valid():
            is_draft = request.POST.get("save_as_draft") == "1"

            product = form.save(commit=False)
            product.is_active = "is_active" in request.POST
            product.is_featured = "is_featured" in request.POST
            product.is_shop_active = "is_shop_active" in request.POST

            if is_draft:
                product.is_active = False

            product.save()

            variant_formset.instance = product
            variants = variant_formset.save()

            if not variants:
                messages.error(request, "Please add at least one variant.")
                return render(request, "product_form.html", {
                    "form": form,
                    "variant_formset": variant_formset,
                    "action": "add",
                    "product": None,
                    "categories": Category.objects.all(),
                })

            first_variant = variants[0]
            save_cropped_images(
                first_variant,
                request.POST.get("cropped_images_json", '[]')
            )

            image_count = count_product_images(product)

            if not is_draft and image_count < 3:
                product.delete()
                messages.error(request, f"Minimum 3 product images are required. You have {image_count}.")
            else:
                messages.success(request, f'"{product.name}" added successfully!')
                return redirect("product_list")
        else:
            messages.error(request, 'Please fix the errors below.')
    else:
        form = ProductForm()
        variant_formset = ProductVariantFormSet(prefix='variants')

    return render(request, 'product_form.html', {
        'form': form,
        'variant_formset': variant_formset,
        'action': 'add',
        'product': None,
        'categories': Category.objects.all(),
    })


@never_cache
@login_required(login_url='admin_login')
def product_edit(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    product = get_object_or_404(
        Product.objects.prefetch_related('variants__images'),
        uuid=uuid
    )
   
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        variant_formset = ProductVariantFormSet(request.POST, instance=product, prefix='variants')

        if form.is_valid() and variant_formset.is_valid():
            is_draft = request.POST.get('save_as_draft') == '1'
            
            removed_image_ids = request.POST.get('removed_image_ids', '[]')
            
            product = form.save(commit=False)
            product.is_active = 'is_active' in request.POST
            product.is_featured = 'is_featured' in request.POST
            product.is_shop_active = 'is_shop_active' in request.POST
            
            if is_draft:
                product.is_active = False
            
            product.save()
            variants = variant_formset.save()
            delete_unused_variant_images(product)
            handle_removed_images(product, removed_image_ids)
            variant = variants[0] if variants else product.variants.first()
            
            if variant:
                save_cropped_images(
                    variant,
                    request.POST.get("cropped_images_json", '[]')
                )
            
            image_count = count_product_images(product)
            
            if not is_draft and image_count < 3:
                messages.error(request, f'Product must have at least 3 images. Currently has {image_count}.')
            else:
                msg = "saved as draft" if is_draft else "updated successfully"
                messages.success(request, f'"{product.name}" {msg}!')
                return redirect("product_list")
        else:
            messages.error(request, 'Please fix the errors below.')
    else:
        form = ProductForm(instance=product)
        variant_formset = ProductVariantFormSet(instance=product, prefix='variants')

    return render(request, 'product_form.html', {
        'form': form,
        'variant_formset': variant_formset,
        'product': product,
        'action': 'edit',
        'categories': Category.objects.all(),
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
        img = ProductImage.objects.get(pk=pk)
        variant = img.variant

        if img.image:
            if os.path.isfile(img.image.path):
                os.remove(img.image.path)
            img.image.delete(save=False)
        
        img.delete()
        for i, rem in enumerate(variant.images.order_by("order")):
            if rem.order != i:
                rem.order = i
                rem.save(update_fields=["order"])

        return JsonResponse({
            "ok": True,
            "remaining": variant.images.count()
        })

    except ProductImage.DoesNotExist:
        return JsonResponse({
            "ok": False,
            "error": "Image not found"
        }, status=404)
    except Exception as e:
        return JsonResponse({
            "ok": False,
            "error": str(e)
        }, status=500)