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
