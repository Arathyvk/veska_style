import re
import logging

from django.contrib import messages
from django.shortcuts import render,redirect
from django.contrib.auth import authenticate, login, logout
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
import uuid as _uuid
from django.urls import reverse
from users.utils import apply_referral_for_new_user, credit_referral_bonus
from users.models import User, ReferralCode
from product_admin.models import Product
from cart_user.models import Cart
 
from core.otp import (
    gen_otp, send_otp_email, is_otp_expired, save_otp_to_session, 
    get_otp_from_session, clear_otp_from_session,
    is_otp_attempts_exceeded, increment_otp_attempts,reset_otp_attempts)

logger = logging.getLogger(__name__)

NAME_REGEX = r"[A-Za-z]+(?: [A-Za-z]+)*"

def is_valid_email(email):
    return re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email)


def home_view(request):
    name = (
        f"{request.user.first_name} {request.user.last_name}"
        if request.user.is_authenticated else ""
    )

    featured_products = (
        Product.objects
        .filter(is_active=True, is_featured=True)
        .prefetch_related('variants__images')
        .order_by('-created_at')[:8]
    )
    for product in featured_products:
        product.offer = product.get_best_offer(product.price)
        product.offer_price = product.discounted_price

    referral_code_obj = None
    referral_link     = None

    if request.user.is_authenticated:
        referral_code_obj = (
            ReferralCode.objects
            .filter(user=request.user, is_active=True)
            .order_by("-created_at")
            .first()
        )

        if referral_code_obj is None:
            referral_code_obj = ReferralCode.objects.create(
                user=request.user,
                code=f"REF{_uuid.uuid4().hex[:8].upper()}",
            )
        signup_path = reverse('signup')
        referral_link = request.build_absolute_uri(f'{signup_path}?ref={referral_code_obj.code}')

    return render(request, "landing.html", {
        "name":     name,
        "products": featured_products,
        "referral_code_obj": referral_code_obj,
        "referral_link": referral_link,
    })


@never_cache
def login_view(request):
    if request.user.is_authenticated and request.user.is_active:
        return redirect("home")

    context = {}
    
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        
        context['email'] = email

        
        if not email and not password:
            messages.error(request, "Please enter your email and password.")
            return render(request, "login.html", context)
        
        if not email:
            messages.error(request, "Please enter your email address.")
            return render(request, "login.html", context)
        
        if not password:
            messages.error(request, "Please enter your password.")
            return render(request, "login.html", context)

        if not is_valid_email(email):
            messages.error(request, "Please enter a valid email address.")
            return render(request, "login.html", context)

        try:
            user_exists = User.objects.filter(email__iexact=email).exists()
        except:
            user_exists = False
        
        user = authenticate(request, username=email, password=password)
        
        if user is None:
            if not user_exists:
                messages.error(request, f'No account found for "{email}". Please check the email or sign up.')
            else:
                messages.error(request, "Incorrect password. Please try again or reset your password.")
            return render(request, "login.html", context)

        if not user.is_active:
            messages.error(request, "Your account has been blocked. Please contact support.")
            return render(request, "login.html", context)

        request.session.set_expiry(1209600 if request.POST.get("remember") else 0)
        old_session_key = request.session.session_key
        
        login(request, user)

        session_cart = Cart.objects.filter(session_key=old_session_key).first()
        user_cart, _ = Cart.objects.get_or_create(user=user)
        
        if session_cart:
            for item in session_cart.items.all():
                user_item, created = user_cart.items.get_or_create(
                    product=item.product,
                    variant=item.variant,
                    defaults={'quantity': item.quantity}
                )
                if not created:
                    user_item.quantity += item.quantity
                    user_item.save()
            session_cart.delete()

        messages.success(request, f"Welcome back, {user.first_name or user.email}!")
        
        next_url = request.GET.get('next')
        if next_url:
            return redirect(next_url)
        return redirect("home")

    return render(request, "login.html", context)


def logout_view(request):
    logout(request)
    return redirect("login")


@never_cache
def signup_view(request):
    errors = {}
    form_data = {}

    ref_code = request.GET.get('ref', '').strip().upper()
    if ref_code:
        request.session['pending_referral_code'] = ref_code
        request.session.modified = True


    if request.method == "POST":
        first_name       = request.POST.get("first_name", "").strip()
        last_name        = request.POST.get("last_name",  "").strip()
        email            = request.POST.get("email",      "").strip().lower()
        password         = request.POST.get("password",   "")
        confirm_password = request.POST.get("confirm_password", "")

        posted_ref = request.POST.get("ref_code", "").strip().upper()
        if posted_ref:
            request.session["pending_referral_code"] = posted_ref
            request.session.modified = True

        form_data = {
            "first_name": first_name, "last_name": last_name, "email": email,
            "ref_code": posted_ref or request.session.get("pending_referral_code", ""),
        }

        if not first_name:
            errors["first_name"] = "First name is required."
        elif not re.fullmatch(r"[A-Za-z]+", first_name):
            errors["first_name"] = "First name must contain only letters."

        if last_name and not re.fullmatch(NAME_REGEX, last_name):
            errors["last_name"] = "Last name must contain only letters and spaces."
        if not email:
            errors["email"] = "Email is required."
        elif User.objects.filter(email=email).exists():
            errors["email"] = "An account with this email already exists."

        pwd_errors = []
        if not password:
            errors["password"] = "Password is required."
        else:
            if len(password) < 8: pwd_errors.append("at least 8 characters")
            if not re.search(r"[A-Za-z]", password): pwd_errors.append("at least one letter")
            if not re.search(r"\d", password): pwd_errors.append("at least one number")
            if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-\+=/\\]", password):
                pwd_errors.append("at least one symbol")
            if pwd_errors:
                errors["password"] = f"Password must contain: {', '.join(pwd_errors)}."

        if not confirm_password:
            errors["confirm_password"] = "Please confirm your password."
        elif password and confirm_password != password:
            errors["confirm_password"] = "Passwords do not match."

        if not errors:
            ref_code = request.session.get("pending_referral_code", "")
            request.session["signup_data"] = {
                "first_name": first_name.capitalize(),
                "last_name":  last_name.capitalize(),
                "email":      email,
                "password":   password,
                "ref_code":   ref_code,
            }

            request.session.modified = True  
            request.session.save()

            otp = gen_otp()
            save_otp_to_session(request, "signup", otp)
            send_otp_email(email, otp)
            return redirect("verify_signup_otp")

    return render(request, "signup.html", {
        "errors": errors, 
        "form_data": form_data,
        "ref_code": request.session.get("pending_referral_code", ""),

        })


@never_cache
def verify_signup_otp(request):
    
    signup_data = request.session.get("signup_data")
 
    if not signup_data:
        messages.error(request, "Session expired. Please sign up again.")
        return redirect("signup")

    if is_otp_attempts_exceeded(request, "signup"):
        messages.error(request, "Too many failed attempts. Please resend the OTP.")
        return render(request, "verify_otp.html", {
            "email": signup_data["email"],
            "max_attempts_exceeded": True,
            "attempts": 3,
            "max_attempts": 3 
        })
 
    if request.method == "POST":
        entered_otp = request.POST.get("otp", "").strip()
        stored_otp, otp_time = get_otp_from_session(request, "signup")

        if not stored_otp:
            messages.error(request, "OTP not found. Please resend.")
            return render(request, "verify_otp.html", {
                "email": signup_data["email"],
                "attempts": request.session.get("signup_otp_attempts", 0),
                "max_attempts": 3,
                "max_attempts_exceeded": False
            })

        elif is_otp_expired(otp_time):
            messages.error(request, "OTP expired. Click Resend OTP.")
            reset_otp_attempts(request, "signup")
            return render(request, "verify_otp.html", {
                "email": signup_data["email"],
                "attempts": 0,
                "max_attempts": 3,
                "max_attempts_exceeded": False
            })

        elif len(entered_otp) < 4:
            messages.error(request, "Please enter the complete 4-digit OTP.")
            attempts = increment_otp_attempts(request, "signup")

            if attempts >= 3:
                messages.error(request, "Too many failed attempts. Please resend the OTP.")
                return render(request, "verify_otp.html", {
                    "email": signup_data["email"],
                    "max_attempts_exceeded": True,
                    "attempts": attempts,
                    "max_attempts": 3
                })
            
            return render(request, "verify_otp.html", {
                "email": signup_data["email"],
                "attempts": attempts,
                "max_attempts": 3,
                "max_attempts_exceeded": False
            })

        elif stored_otp != entered_otp:
            attempts = increment_otp_attempts(request, "signup")
            remaining = 3 - attempts

            if remaining > 0:
                messages.error(request, f"Incorrect OTP. {remaining} attempt(s) remaining.")
            else:
                messages.error(request, "Too many failed attempts. Please resend the OTP.")

            if attempts >= 3:
                return render(request, "verify_otp.html", {
                    "email": signup_data["email"],
                    "max_attempts_exceeded": True,
                    "attempts": attempts,
                    "max_attempts": 3
                })
            
            return render(request, "verify_otp.html", {
                "email": signup_data["email"],
                "attempts": attempts,
                "max_attempts": 3,
                "max_attempts_exceeded": False
            })

        else:
            reset_otp_attempts(request, "signup")

            existing_user = User.objects.filter(email=signup_data["email"]).first()

            if existing_user:
                messages.error(request, "An account with this email already exists. Please log in.")
                request.session.pop("signup_data", None)
                clear_otp_from_session(request, "signup")
                return redirect("login")

            user = User.objects.create_user(
                email=signup_data["email"],
                password=signup_data["password"],
                first_name=signup_data["first_name"],
                last_name=signup_data.get("last_name", ""),
                is_staff=False,
                is_superuser=False,
            )

            ref_code = signup_data.get("ref_code") or request.session.pop("pending_referral_code", None)
            request.session.pop("pending_referral_code", None)
            apply_referral_for_new_user(user, ref_code)
            ref_code = request.session.pop("pending_referral_code", None)
            if ref_code:
                try:
                    referral = ReferralCode.objects.get(code=ref_code, is_active=True)
                    user.referred_by = referral
                    user.save(update_fields=["referred_by"])
                    credit_referral_bonus(
                        referrer=referral.user,
                        referred_user=user,
                        referral_code=referral,
                    )
                except ReferralCode.DoesNotExist:
                    logger.info(
                        "Signup for %s used invalid/expired referral code: %s",
                        user.email, ref_code,
                    )    

            request.session.pop("signup_data", None)
            clear_otp_from_session(request, "signup")
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, f"Welcome to Veska, {user.first_name}!")
            return redirect("login")
    
    attempts = request.session.get("signup_otp_attempts", 0)
    return render(request, "verify_otp.html", {
        "email": signup_data["email"],
        "attempts": attempts,
        "max_attempts": 3,
        "max_attempts_exceeded": attempts >= 3
    })
 
 
@never_cache
@require_POST
def resend_otp(request):
    purpose = request.POST.get("purpose", "signup")
    
    if purpose == "signup":
        signup_data = request.session.get("signup_data")
        if not signup_data:
            return JsonResponse(
                {"success": False, "message": "Session expired. Please sign up again."}
            )
        email = signup_data.get("email")

    otp = gen_otp()
    save_otp_to_session(request, purpose, otp)  
    send_otp_email(email, otp)
    
    return JsonResponse({
        "success": True, 
        "message": "OTP sent successfully.",
        "max_attempts": 3
    })

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
        
    if is_otp_attempts_exceeded(request, "forgot"):
        messages.error(request, "Too many failed attempts. Please request a new OTP.")
        return render(request, "forgot_verify_otp.html", {
            "email": email,
            "purpose": "forgot",
            "max_attempts_exceeded": True,
            "attempts": 3,
            "max_attempts": 3
        })
    
    if request.method == "POST":

        entered_otp = request.POST.get("otp", "").strip()
        stored_otp, otp_time = get_otp_from_session(request, "forgot")
        
        if not stored_otp:
            messages.error(request, "OTP not found. Please request a new one.")
        elif is_otp_expired(otp_time):
            messages.error(request, "OTP has expired. Please click Resend code.")
            reset_otp_attempts(request, "forgot")
        elif len(entered_otp) < 4:
            messages.error(request, "Please enter the complete 4-digit code.")
            attempts = increment_otp_attempts(request, "forgot")
            if attempts >= 3:
                messages.error(request, "Too many failed attempts. Please request a new OTP.")
                return render(request, "forgot_verify_otp.html", {
                    "email": email,
                    "purpose": "forgot",
                    "max_attempts_exceeded": True,
                    "attempts": attempts,
                    "max_attempts": 3
                })
        elif stored_otp != entered_otp:
            attempts = increment_otp_attempts(request, "forgot")
            remaining = 3 - attempts
            messages.error(request, f"Incorrect code. {remaining} attempt(s) remaining.")
            
            if attempts >= 3:
                messages.error(request, "Too many failed attempts. Please request a new OTP.")
                return render(request, "forgot_verify_otp.html", {
                    "email": email,
                    "purpose": "forgot",
                    "max_attempts_exceeded": True,
                    "attempts": attempts,
                    "max_attempts": 3
                })
        else:
            reset_otp_attempts(request, "forgot")
            clear_otp_from_session(request, "forgot")
            request.session["forgot_verified"] = True
            return redirect("reset_password")
    
    attempts = request.session.get("forgot_otp_attempts", 0)
    return render(request, "forgot_verify_otp.html", {
        "email": email,
        "purpose": "forgot",
        "attempts": attempts,
        "max_attempts": 3,
        "max_attempts_exceeded": attempts >= 3
    })


@never_cache
@require_POST
def forgot_resend_otp(request):
    purpose = request.POST.get("purpose", "forgot")
    
    if purpose == "forgot":
        email = request.session.get("forgot_email")

        if not email:
            return JsonResponse({"success": False, "message": "Session expired. Please try again."})

    elif purpose == "signup":  
        signup_data = request.session.get("signup_data")

        if not signup_data:
            return JsonResponse({"success": False, "message": "Session expired. Please sign up again."})
        email = signup_data.get("email")

    else:
        return JsonResponse({"success": False, "message": "Invalid request."})
    
    otp = gen_otp()
    save_otp_to_session(request, purpose, otp)  
    send_otp_email(email, otp)
    
    return JsonResponse({
        "success": True,
        "message": "A new code has been sent.",
        "max_attempts": 3
    })

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



def debug_social(request):
    site = Site.objects.get(id=1)
    apps = SocialApp.objects.filter(sites=site)

    return HttpResponse(f"Apps: {apps}")


def error_400(request, exception=None):
    return render(request, 'errors/400.html', status=400)


def error_403(request, exception=None):
    return render(request, 'errors/403.html', status=403)


def error_404(request, exception=None):
    return render(request, 'errors/404.html', status=404)


def error_500(request):
    return render(request, 'errors/500.html', status=500)
