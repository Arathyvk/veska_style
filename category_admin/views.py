from django.shortcuts import render,redirect
from django.core.paginator import Paginator
from django.contrib import messages

 
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
 