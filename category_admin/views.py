from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.views.decorators.cache import never_cache

from category_admin.models import Category
from .forms  import CategoryForm


def is_admin(user):
    return user.is_authenticated and user.is_staff


@never_cache
@login_required(login_url='admin_login')
def category_list(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    query = request.GET.get('q', '').strip()
    sort  = request.GET.get('sort', 'desc')

    categories = Category.objects.all()   
    if query:
        categories = categories.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )

    categories = categories.order_by(
        'created_at' if sort == 'asc' else '-created_at'
    )

    paginator = Paginator(categories, 10)
    page      = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'category_list.html', {
        'categories': page,
        'query':      query,
        'sort':       sort,
    })


@never_cache
@login_required(login_url='admin_login')
def category_add(request):
    if not is_admin(request.user):
        return redirect('admin_login')

    form = CategoryForm(request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            try:
                category = form.save()
            except Exception as e:
                print("ERROR:", e)
                messages.error(request, str(e))

            messages.success(request, f'"{category.name}" added successfully!')
            return redirect('category_list')
        else:
            messages.error(request, 'Please fix the errors below.')

    return render(request, 'category_form.html', {'form': form, 'action': 'add'})


@never_cache
@login_required(login_url='admin_login')
def category_edit(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    category = get_object_or_404(Category, uuid=uuid)
    form     = CategoryForm(instance=category)

    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            category = form.save()
            messages.success(request, f'"{category.name}" updated successfully!')
            return redirect('category_list')
        else:
            messages.error(request, 'Please fix the errors below.')

    return render(request, 'category_form.html', {
        'form': form, 'category': category, 'action': 'edit'
    })


@never_cache
@login_required(login_url='admin_login')
def category_block(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    category = get_object_or_404(Category, uuid=uuid)
    if request.method == 'POST':
        category.block()
        messages.success(request, f'"{category.name}" has been blocked.')
    return redirect('category_list')


@never_cache
@login_required(login_url='admin_login')
def category_unblock(request, uuid):
    if not is_admin(request.user):
        return redirect('admin_login')

    category = get_object_or_404(Category, uuid=uuid)
    if request.method == 'POST':
        category.unblock()
        messages.success(request, f'"{category.name}" has been unblocked.')
    return redirect('category_list')