import re
import base64
import cloudinary.uploader
 
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.http import JsonResponse
 
from .models import Address
from core.otp import gen_otp, send_otp_email, is_otp_expired, save_otp_to_session, get_otp_from_session, clear_otp_from_session


def is_google_user(user):
    try:
        return user.socialaccount_set.filter(provider='google').exists()
    except Exception:
        return False
    

@login_required
@never_cache
def account_profile(request):
    user = request.user

    if request.method == "POST":
        first_name    = request.POST.get("first_name", "").strip()
        last_name     = request.POST.get("last_name",  "").strip()
        phone         = request.POST.get("phone_number", "").strip()
        cropped_photo = request.POST.get("cropped_photo", "").strip()

        errors = []

        if not first_name:
            errors.append("First name is required.")
        elif not re.fullmatch(r"[A-Za-z]+", first_name):
            errors.append("First name must contain only letters.")

        if last_name and not re.fullmatch(r"[A-Za-z]+", last_name):
            errors.append("Last name must contain only letters.")

        if phone and not re.fullmatch(r"[\d\s\+\-\(\)]{7,15}", phone):
            errors.append("Please enter a valid phone number.")

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, "account_profile.html")

        user.first_name   = first_name.capitalize()
        user.last_name    = last_name.capitalize() if last_name else ""
        user.phone_number = phone

        if cropped_photo:
            try:
                if ',' in cropped_photo:
                    cropped_photo = cropped_photo.split(',')[1]

                image_bytes = base64.b64decode(cropped_photo)

                result = cloudinary.uploader.upload(
                    image_bytes,
                    folder="profile_photos",
                    public_id=f"profile_{user.pk}",
                    overwrite=True,
                    crop="fill",
                    width=400,
                    height=400,
                    resource_type="image",
                )

                user.profile_pic = result['secure_url']  
            except Exception as e:
                print("=== CLOUDINARY ERROR ===", str(e))
                messages.error(request, f"Failed to save photo: {str(e)}")
                return render(request, "account_profile.html")

        user.save()
        messages.success(request, "Profile updated successfully.")
        return redirect("account_profile")

    return render(request, "account_profile.html")


@login_required
@never_cache
def account_address(request):
    addresses = Address.objects.filter(user=request.user)
    return render(request, "account_address.html", {"addresses": addresses})
 


@login_required
@never_cache
def account_address_add(request):
    if request.method == "POST":
        errors        = []
        full_name     = request.POST.get("full_name",     "").strip()
        phone         = request.POST.get("phone",         "").strip()
        address_line1 = request.POST.get("address_line1", "").strip()
        address_line2 = request.POST.get("address_line2", "").strip()
        city          = request.POST.get("city",          "").strip()
        state         = request.POST.get("state",         "").strip()
        pincode       = request.POST.get("pincode",       "").strip()
        country       = request.POST.get("country",       "India").strip()
        is_default    = request.POST.get("is_default") == "on"
 
        if not full_name:     errors.append("Full name is required.")
        if not phone:         errors.append("Phone number is required.")
        if not address_line1: errors.append("Address line 1 is required.")
        if not city:          errors.append("City is required.")
        if not state:         errors.append("State is required.")
        if not pincode:
            errors.append("Pincode is required.")
        elif not re.fullmatch(r"\d{6}", pincode):
            errors.append("Pincode must be 6 digits.")
        if Address.objects.filter(user=request.user).count() >= 3:
            errors.append("You can save up to 3 addresses only.")
 
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, "account_address_form.html",
                          {"form_data": request.POST, "action": "add"})
 
        Address.objects.create(
            user=request.user,
            full_name=full_name, 
            phone=phone,
            address_line1=address_line1, 
            address_line2=address_line2,
            city=city, state=state, 
            pincode=pincode,
            country=country, 
            is_default=is_default,
        )
        messages.success(request, "Address added successfully.")
        return redirect("account_address")
 
    return render(request, "account_address_form.html", {"action": "add", "form_data": {}, "address" : None})
 

@login_required
@never_cache
def account_change_email(request):
    user = request.user
    google = is_google_user(user)
 
    if request.method == "POST" and not google:
        new_email = request.POST.get("new_email", "").strip().lower()
        password  = request.POST.get("password",  "").strip()
 
        errors = []
 
        if not new_email:
            errors.append("Please enter a new email address.")
        elif not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', new_email):
            errors.append("Please enter a valid email address.")
        elif new_email == user.email:
            errors.append("New email must be different from your current email.")
        else:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
                errors.append("This email is already registered to another account.")
 
        if not password:
            errors.append("Please enter your current password.")
        elif not user.check_password(password):
            errors.append("Current password is incorrect.")
 
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, "account_change_email.html",
                          {"is_google_user": google, "step": "enter"})
 
        otp = gen_otp()
        request.session["pending_email"] = new_email
        save_otp_to_session(request, "email_change", otp)
        send_otp_email(new_email, otp, subject="Veska — Verify Your New Email")
        return redirect("account_change_email_verify")
 
    return render(request, "account_change_email.html",
                  {"is_google_user": google, "step": "enter"})
 

@login_required
@never_cache
def account_change_email_verify(request):
    user      = request.user
    google    = is_google_user(user)
    new_email = request.session.get("pending_email")
 
    if google or not new_email:
        return redirect("account_change_email")
 
    if request.method == "POST":
        entered_otp = request.POST.get("otp", "").strip()
        stored_otp, otp_time = get_otp_from_session(request, "email_change")
 
        if not stored_otp:
            messages.error(request, "OTP not found. Please request a new one.")
        elif is_otp_expired(otp_time):
            messages.error(request, "OTP expired. Please request a new code.")
        elif not entered_otp or len(entered_otp) < 4:
            messages.error(request, "Please enter the complete 4-digit code.")
        elif stored_otp != entered_otp:
            messages.error(request, "Incorrect OTP. Please try again.")
        else:
            clear_otp_from_session(request, "email_change")
            request.session.pop("pending_email", None)
            user.email = new_email
            user.save()
            messages.success(request, f"Email updated to {new_email} successfully.")
            return redirect("account_profile")
 
    return render(request, "account_change_email.html", {
        "is_google_user": google,
        "step":      "otp",
        "new_email": new_email,
    })
 

@login_required
@require_POST
def account_change_email_resend(request):
    new_email = request.session.get("pending_email")
    if not new_email:
        return JsonResponse({"success": False, "message": "Session expired. Please start again."})
 
    otp = gen_otp()
    save_otp_to_session(request, "email_change", otp)
    send_otp_email(new_email, otp, subject="Veska — Verify Your New Email")
    return JsonResponse({"success": True})
 