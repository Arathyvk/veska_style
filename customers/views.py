import re
import base64
import cloudinary.uploader

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache


@login_required
@never_cache
def account_profile(request):
    user = request.user

    if request.method == "POST":
        first_name    = request.POST.get("first_name", "").strip()
        last_name     = request.POST.get("last_name",  "").strip()
        phone         = request.POST.get("phone_number", "").strip()
        cropped_photo = request.POST.get("cropped_photo", "").strip()

        print("=== PROFILE POST DEBUG ===")
        print("first_name:", first_name)
        print("cropped_photo length:", len(cropped_photo))
        print("==========================")

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

                print("=== CLOUDINARY RESULT ===")
                print("public_id :", result['public_id'])
                print("secure_url:", result['secure_url'])
                print("=========================")

                user.profile_pic = result['secure_url']  
            except Exception as e:
                print("=== CLOUDINARY ERROR ===", str(e))
                messages.error(request, f"Failed to save photo: {str(e)}")
                return render(request, "account_profile.html")

        user.save()
        messages.success(request, "Profile updated successfully.")
        return redirect("account_profile")

    return render(request, "account_profile.html")