from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST

 
from .models import Category
 
 
ITEMS_PER_PAGE = 10
 
 
def category_list(request):
    query = request.GET.get('q', '').strip()
 
    qs = Category.objects.order_by('-created_at')     
    if query:
        qs = qs.filter(name__icontains=query)
 
    paginator   = Paginator(qs, ITEMS_PER_PAGE)         
    page_number = request.GET.get('page', 1)
    page_obj    = paginator.get_page(page_number)
 
    return render(request, 'category_list.html', {
        'page_obj'  : page_obj,
        'query'     : query,
        'total'     : paginator.count,
    })



def category_add(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Category name cannot be empty.')
        elif Category.objects.filter(name__iexact=name, is_deleted=False).exists():
            messages.error(request, f'Category "{name}" already exists.')
        else:
            Category.objects.create(name=name)
            messages.success(request, f'Category "{name}" added successfully.')
            return redirect('admin_category_list')
 
    return render(request, 'category_add.html')
 

def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk, is_deleted=False)
 
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Category name cannot be empty.')
        elif (
            Category.objects
            .filter(name__iexact=name, is_deleted=False)
            .exclude(pk=pk)
            .exists()
        ):
            messages.error(request, f'Category "{name}" already exists.')
        else:
            category.name = name
            category.save(update_fields=['name', 'updated_at'])
            messages.success(request, f'Category updated to "{name}".')
            return redirect('admin_category_list')
 
    return render(request, 'category_edit.html', {'category': category})
 
 

@require_POST
def category_block(request, pk):
    category = get_object_or_404(Category, pk=pk)
    category.soft_delete()  
    messages.success(request, f'Category "{category.name}" has been blocked.')
    return redirect('admin_category_list')


@require_POST
def category_unblock(request, pk):
    category = get_object_or_404(Category, pk=pk)
    category.restore()  
    messages.success(request, f'Category "{category.name}" has been unblocked.')
    return redirect('admin_category_list')