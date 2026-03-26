from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model          
from django.views.decorators.cache import never_cache
from django.core.paginator import Paginator
from django.db.models import Q




User = get_user_model()  



def is_admin_user(user):
    return user.is_authenticated and user.is_staff


@never_cache
def admin_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('user_list')

    error = {}

    if request.method == 'POST':
        email    = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()

        if not email or not password:
            error['field'] = "Both email and password are required."
        else:
            user = authenticate(request, email=email, password=password)

            if user and user.is_staff and user.is_active:
                login(request, user)
                return redirect('user_list')
            else:
                error['invalid'] = "Invalid credentials or not an admin."

    return render(request, 'admin_login.html', {'error': error})


@never_cache
def admin_logout(request):
    logout(request)
    return redirect('admin_login')

@never_cache
def user_list(request):
    if not is_admin_user(request.user):
        return redirect('admin_login')

    query = request.GET.get('q', '').strip()
    sort  = request.GET.get('sort', 'desc')  

    order = 'date_joined' if sort == 'asc' else '-date_joined'
    users = User.objects.filter(is_superuser=False).order_by(order)

    if query:
        users = users.filter(
            Q(username__icontains=query)   |
            Q(email__icontains=query)      |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )

    paginator = Paginator(users, 10)
    page      = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'user_list.html', {
        'users': page,
        'query': query,
        'sort':  sort,
    })