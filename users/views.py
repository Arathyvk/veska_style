import re
from django.contrib import messages
from django.shortcuts import render,redirect
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.http import require_POST


from .models import User
from django.core.exceptions import ValidationError
 
from core.otp import gen_otp, send_otp_email, is_otp_expired, save_otp_to_session, get_otp_from_session, clear_otp_from_session


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

    if request.method == "POST":
        import re
        first_name       = request.POST.get("first_name", "").strip()
        last_name        = request.POST.get("last_name",  "").strip()
        email            = request.POST.get("email",      "").strip().lower()
        password         = request.POST.get("password",   "")
        confirm_password = request.POST.get("confirm_password", "")

        form_data = {"first_name": first_name, "last_name": last_name, "email": email}

        if not first_name:
            errors["first_name"] = "First name is required."
        elif not re.fullmatch(r"[A-Za-z]+", first_name):
            errors["first_name"] = "First name must contain only letters."

        if last_name and not re.fullmatch(r"[A-Za-z]+", last_name):
            errors["last_name"] = "Last name must contain only letters."

        if not email:
            errors["email"] = "Email is required."
        elif User.objects.filter(email=email).exists():
            errors["email"] = "An account with this email already exists."

        pwd_errors = []
        if not password:
            errors["password"] = "Password is required."
        else:
            if len(password) < 8:          pwd_errors.append("at least 8 characters")
            if not re.search(r"[A-Za-z]", password): pwd_errors.append("at least one letter")
            if not re.search(r"\d", password):       pwd_errors.append("at least one number")
            if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-\+=/\\]", password):
                pwd_errors.append("at least one symbol")
            if pwd_errors:
                errors["password"] = f"Password must contain: {', '.join(pwd_errors)}."

        if not confirm_password:
            errors["confirm_password"] = "Please confirm your password."
        elif password and confirm_password != password:
            errors["confirm_password"] = "Passwords do not match."

        if not errors:
            request.session["signup_data"] = {
                "first_name": first_name.capitalize(),
                "last_name":  last_name.capitalize(),
                "email":      email,
                "password":   password,
            }
            otp = gen_otp()
            save_otp_to_session(request, "signup", otp)
            send_otp_email(email, otp)
            return redirect("verify_signup_otp")

    return render(request, "signup.html", {"errors": errors, "form_data": form_data})


def verify_signup_otp(request):
    data = request.session.get("signup_data")
    if not data:
        messages.error(request, "Session expired. Please sign up again.")
        return redirect("signup")

    if request.method == "POST":

        entered = request.POST.get("otp", "").strip()

        stored_otp, otp_time = get_otp_from_session(request, "signup")

        if not stored_otp:
            messages.error(request, "OTP not found. Please resend.")
        elif is_otp_expired(otp_time):
            messages.error(request, "OTP expired. Click Resend OTP.")
        elif len(entered) < 4:
            messages.error(request, "Please enter the complete 4-digit OTP.")
        elif stored_otp != entered:
            messages.error(request, "Incorrect OTP. Please try again.")
        else:
            user = User.objects.create_user(
                email      = data["email"],
                password   = data["password"],
                first_name = data["first_name"],
                last_name  = data.get("last_name", ""),
            )
            request.session.pop("signup_data", None)
            clear_otp_from_session(request, "signup")
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, f"Welcome to Veska, {user.first_name}!")
            return redirect("home")

    return render(request, "signup_otp.html", {"email": data["email"]})


@require_POST
def resend_otp(request):
    purpose = request.POST.get("purpose", "signup")

    if purpose == "signup":
        data  = request.session.get("signup_data")
        email = data["email"] if data else None
    elif purpose == "forgot":
        email = request.session.get("forgot_email")
    else:
        return JsonResponse({"success": False, "message": "Invalid request."})

    if not email:
        return JsonResponse({"success": False, "message": "Session expired."})

    otp     = gen_otp()
    subject = "Veska — Reset Password OTP" if purpose == "forgot" else "Veska — Verify your email"
    save_otp_to_session(request, purpose, otp)
    send_otp_email(email, otp, subject=subject)
    return JsonResponse({"success": True, "message": f"OTP resent to {email}."})
 

def forgot_password(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        if not email:
            messages.error(request, "Please enter your email.")
        elif not User.objects.filter(email=email).exists():
            messages.error(request, "No account found with this email.")
        else:
            otp = gen_otp()
            request.session["forgot_email"] = email
            save_otp_to_session(request, "forgot", otp)
            send_otp_email(email, otp, subject="Veska — Reset Password OTP")
            return redirect("verify_forgot_otp")

    return render(request, "forgot_password.html")
 
