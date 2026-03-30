from django.shortcuts        import render
from django.core.paginator   import Paginator
 
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
 