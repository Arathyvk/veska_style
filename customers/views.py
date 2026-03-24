import re
import base64
import cloudinary.uploader
 
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
 
from .models import Address

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
 