import re
from django.contrib import messages
from django.shortcuts import render,redirect
from django.contrib.auth import authenticate, login, logout

from .models import User
from django.core.exceptions import ValidationError



def is_valid_email(email):
    return re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email)


def home_view(request):
    name = f"{request.user.first_name} {request.user.last_name}" if request.user.is_authenticated else ""
    context = {
        "name" : name,
    }    
    
    return render(request, "landing.html", context)

def login_view(request):
    if request.user.is_authenticated and request.user.is_active:
        return redirect("home")

    if request.method == "POST":
        email    = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")

        if not email and not password:
            messages.error(request, "Please enter your email and password.")
            return render(request, "login.html")
        if not email:
            messages.error(request, "Please enter your email address.")
            return render(request, "login.html")
        if not password:
            messages.error(request, "Please enter your password.")
            return render(request, "login.html")

        if not is_valid_email(email):
            messages.error(request, "Please enter a valid email address (e.g. hello@example.com).")
            return render(request, "login.html")

    
        try:
            User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, f'No account found for "{email}". Please check the email or sign up.')
            return render(request, "login.html")

     
        user = authenticate(request, email=email, password=password)
        if user is None:
            messages.error(request, "Incorrect password. Please try again or reset your password.")
            return render(request, "login.html")

        if not user.is_active:
            messages.error(request, "Your account has been blocked. Please contact support.")
            return render(request, "login./html")

        request.session.set_expiry(1209600 if request.POST.get("remember") else 0)

        login(request, user)
        messages.success(request, f"Welcome back, {user.first_name or user.email}!")
        return redirect("home")

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("login")



def signup_view(request):
    errors = {}
    form_data = {}

    if request.method == 'POST':
        first_name       = request.POST.get('first_name', '').strip()
        last_name        = request.POST.get('last_name', '').strip()
        email            = request.POST.get('email', '').strip().lower()
        password         = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        form_data = {
            'first_name': first_name,
            'last_name':  last_name,
            'email':      email,
        }

        if not first_name:
            errors['first_name'] = "First name is required."
        elif not re.fullmatch(r'[A-Za-z]+', first_name):
            errors['first_name'] = "First name must contain only letters (A–Z, a–z)."

        if last_name and not re.fullmatch(r'[A-Za-z]+', last_name):
            errors['last_name'] = "Last name must contain only letters (A–Z, a–z)."

        if not email:
            errors['email'] = "Email is required."
        elif not re.fullmatch(r'^[\w\.\+\-]+@[\w\-]+\.[a-z]{2,}$', email):
            errors['email'] = "Enter a valid email address."
        elif User.objects.filter(email=email).exists():
            errors['email'] = "An account with this email already exists."

        pwd_errors = []
        if not password:
            errors['password'] = "Password is required."
        else:
            if len(password) < 8:
                pwd_errors.append("at least 8 characters")
            if not re.search(r'[A-Za-z]', password):
                pwd_errors.append("at least one letter")
            if not re.search(r'\d', password):
                pwd_errors.append("at least one number")
            if not re.search(r'[!@#$%^&*(),.?\":{}|<>_\-\+=/\\]', password):
                pwd_errors.append("at least one symbol (!@#$%...)")
            if pwd_errors:
                errors['password'] = f"Password must contain: {', '.join(pwd_errors)}."

        if not confirm_password:
            errors['confirm_password'] = "Please confirm your password."
        elif password and confirm_password != password:
            errors['confirm_password'] = "Passwords do not match."

        if not errors:
            user = User.objects.create_user(
                email      = email,
                first_name = first_name.capitalize(),
                last_name  = last_name.capitalize(),
                password   = password,
            )
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, "Account created successfully! Welcome.")
            return redirect('home')

    return render(request, 'signup.html', {'errors': errors, 'form_data': form_data})