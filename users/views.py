import re

from django.contrib import messages
from django.shortcuts import render,redirect
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache


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

@never_cache
def login_view(request):
    if request.user.is_authenticated and request.user.is_active:
        return redirect("home")

    if request.method == "POST":
        print("reached the line")
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
            return render(request, "login.html")

        request.session.set_expiry(1209600 if request.POST.get("remember") else 0)

        login(request, user)
        messages.success(request, f"Welcome back, {user.first_name or user.email}!")
        return redirect("home")

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("login")



@never_cache
def signup_view(request):
    errors = {}
    form_data = {}

    if request.method == "POST":
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

            request.session.modified = True  
            request.session.save()

            otp = gen_otp()
            save_otp_to_session(request, "signup", otp)
            send_otp_email(email, otp)
            return redirect("verify_signup_otp")

    return render(request, "signup.html", {"errors": errors, "form_data": form_data})



@never_cache
def verify_signup_otp(request):
    
    signup_data = request.session.get("signup_data")
 
    if not signup_data:
        messages.error(request, "Session expired. Please sign up again.")
        return redirect("signup")
 
    if request.method == "POST":
        entered_otp = request.POST.get("otp", "").strip()
        stored_otp, otp_time = get_otp_from_session(request, "signup")

        print("Entered OTP:", entered_otp)
        print("Stored OTP:", stored_otp)
        print("OTP time:", otp_time)
        print("Is expired:", is_otp_expired(otp_time))
 
        if not stored_otp:
            messages.error(request, "OTP not found. Please resend.")
 
        elif is_otp_expired(otp_time):
            messages.error(request, "OTP expired. Click Resend OTP.")
 
        elif len(entered_otp) < 4:
            messages.error(request, "Please enter the complete 4-digit OTP.")
 
        elif stored_otp != entered_otp:
            messages.error(request, "Incorrect OTP. Please try again.")
 
        else:
            user = User.objects.create_user(
                email=signup_data["email"],
                password=signup_data["password"],
                first_name=signup_data["first_name"],
                last_name=signup_data.get("last_name", ""),
            )
            request.session.pop("signup_data", None)
            clear_otp_from_session(request, "signup")
            messages.success(request, f"Welcome to Veska, {user.first_name}!")
            return redirect("login")
 
    return render(request, "verify_otp.html", {"email": signup_data["email"]})
 
 
@never_cache
@require_POST
def resend_otp(request):
    purpose = request.POST.get("purpose", "signup")
    print("Resend called for purpose:", purpose)
    print("Session before resend:", dict(request.session))

    if purpose == "signup":
        signup_data = request.session.get("signup_data")
        print("signup_data:", signup_data)
        if not signup_data:
            return JsonResponse(
                {"success": False, "message": "Session expired. Please sign up again."}
            )
        email = signup_data.get("email")

    otp = gen_otp()
    print("New OTP generated:", otp)
    save_otp_to_session(request, purpose, otp)
    print("Session after save:", dict(request.session))
    send_otp_email(email, otp)

    return JsonResponse({"success": True, "message": "OTP sent successfully."})


@never_cache
def forgot_password(request):
    if request.user.is_authenticated:
        return redirect("home")
 
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
 
        if not email:
            messages.error(request, "Please enter your email address.")
        elif not is_valid_email(email):
            messages.error(request, "Please enter a valid email address.")
        elif not User.objects.filter(email=email).exists():
            messages.error(request, "No account found with this email.")
        else:
            otp = gen_otp()
            request.session["forgot_email"] = email
            request.session.pop("forgot_verified", None)  
            request.session.modified = True
            save_otp_to_session(request, "forgot", otp)
            send_otp_email(email, otp, subject="Veska — Reset Password OTP")
            messages.success(request, f"A 4-digit code has been sent to {email}.")
            return redirect("verify_forgot_otp")
 
    return render(request, "forgot_password.html")
 
 
@never_cache
def verify_forgot_otp(request):
    email = request.session.get("forgot_email")
    if not email:
        messages.error(request, "Session expired. Please enter your email again.")
        return redirect("forgot_password")
 
    if request.method == "POST":
        entered_otp = request.POST.get("otp", "").strip()
        stored_otp, otp_time = get_otp_from_session(request, "forgot")

        print("Entered OTP:", entered_otp)
        print("Stored OTP:", stored_otp)
        print("OTP time:", otp_time)
        print("Is expired:", is_otp_expired(otp_time))
 
 
        if not stored_otp:
            messages.error(request, "OTP not found. Please request a new one.")
        elif is_otp_expired(otp_time):
            messages.error(request, "OTP has expired. Please click Resend code.")
        elif len(entered_otp) < 4:
            messages.error(request, "Please enter the complete 4-digit code.")
        elif stored_otp != entered_otp:
            messages.error(request, "Incorrect code. Please try again.")
        else:
            clear_otp_from_session(request, "forgot")
            request.session["forgot_verified"] = True
            request.session["forgot_verified"] = True
            return redirect("reset_password")
 
    return render(request, "forgot_verify_otp.html", {"email": email, "purpose": "forgot"})
 
 

@never_cache
@require_POST
def forgot_resend_otp(request):
    purpose = request.POST.get("purpose", "forgot")
   
    if purpose == "forgot":
        email = request.session.get("forgot_email")
        if not email:
            return JsonResponse({"success": False, "message": "Session expired. Please try again."})
 
    elif purpose == "forgot":
        forgot_data = request.session.get("signup_data")
        if not forgot_data:
            return JsonResponse({"success": False, "message": "Session expired. Please sign up again."})
        email = forgot_data.get("email")
 
    else:
        return JsonResponse({"success": False, "message": "Invalid request."})
 
    otp = gen_otp()
    save_otp_to_session(request, purpose, otp)
    send_otp_email(email, otp)
 
    return JsonResponse({"success": True, "message": "A new code has been sent."})
 

@never_cache
def reset_password(request):
    if not request.session.get("forgot_verified"):
        messages.error(request, "Please verify your email first.")
        return redirect("forgot_password")
 
    if request.method == "POST":
        password         = request.POST.get("password", "").strip()
        confirm_password = request.POST.get("confirm_password", "").strip()
        email            = request.session.get("forgot_email")
 
        errors = []
 
        if not password:
            errors.append("Password is required.")
        else:
            rules = []
            if len(password) < 8:
                rules.append("at least 8 characters")
            if not re.search(r"[A-Za-z]", password):
                rules.append("at least one letter")
            if not re.search(r"\d", password):
                rules.append("at least one number")
            if not re.search(r'[!@#$%^&*(),.?\":{}|<>_\-\+=/\\]', password):
                rules.append("at least one symbol")
            if rules:
                errors.append(f"Password must contain: {', '.join(rules)}.")
 
        if not confirm_password:
            errors.append("Please confirm your new password.")
        elif password and confirm_password != password:
            errors.append("Passwords do not match.")
 
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, "reset_password.html")
 
        try:
            user = User.objects.get(email=email)
            user.set_password(password)
            user.save()
            request.session.pop("forgot_verified", None)
            request.session.pop("forgot_email", None)
            messages.success(request, "Password updated successfully. Please log in.")
            return redirect("login")
        except User.DoesNotExist:
            messages.error(request, "Account not found. Please try again.")
            return redirect("forgot_password")
 
    return render(request, "reset_password.html")
 