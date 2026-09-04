import re
import base64
import cloudinary.uploader
import cloudinary.api
import random
import string
import uuid as _uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.core.mail import send_mail

from customers.models import Address
from users.models import ReferralCode
from offer_admin.models import BaseOffer

User = get_user_model()

NAME_REGEX = r"[A-Za-z]+(?: [A-Za-z]+)*"

def _is_google_user(user):
    try:
        return user.socialaccount_set.filter(provider='google').exists()
    except AttributeError:
        return False

def _has_usable_password(user):
    return user.has_usable_password()

def _generate_otp(length=4):
    return ''.join(random.choices(string.digits, k=length))

def _send_email_otp(new_email, otp):
    send_mail(
        subject="Your Email Verification Code",
        message=(
            "Dear Customer,\n\n"
            "Thank you for updating your email address.\n\n"
            f"Your email verification code is: {otp}\n\n"
            "This verification code is valid for 2 minutes. "
            "Please do not share this code with anyone for security reasons.\n\n"
            "If you did not request this email address change, "
            "please ignore this message or contact our support team "
            "if you believe your account may be at risk.\n\n"
            "Best regards,\n"
            "VESKA Team"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[new_email],
        fail_silently=False,
    )

def _delete_cloudinary_image(public_id):
    if public_id:
        try:
            cloudinary.uploader.destroy(public_id)
            return True
        except Exception as e:
            return False
    return False

def _upload_profile_photo(user, image_data):
    try:
        result = cloudinary.uploader.upload(
            image_data,
            folder="profile_photos",
            public_id=f"profile_{user.pk}",
            overwrite=True,
            crop="fill",
            width=400,
            height=400,
            resource_type="image",
        )
        return result["public_id"], None
    except Exception as e:
        return None, str(e)


def _profile_referral_context(request, user):
    referral_code, _ = ReferralCode.objects.get_or_create(
        user=user,
        is_active=True,
        defaults={'code': f'REF{_uuid.uuid4().hex[:8].upper()}'},
    )
    referral_offer = BaseOffer.objects.filter(
        offer_type='REFERRAL', is_active=True,
        start_date__lte=timezone.now(), end_date__gte=timezone.now(),
    ).order_by('-created_at').first()
    return {
        'referral_code': referral_code,
        'referral_offer': referral_offer,
        'referral_link': request.build_absolute_uri(
            f'{reverse("signup")}?ref={referral_code.code}'
        ),
    }


@login_required
@never_cache
def account_profile(request):
    user = request.user

    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        phone = request.POST.get("phone_number", "").strip()

     
        cropped_photo = request.POST.get("cropped_photo", "").strip()
        remove_photo = request.POST.get("remove_photo", "").strip()

        errors = []

        # =========================
        # PERSONAL INFORMATION VALIDATION
        # =========================

        if not first_name:
            errors.append("First name is required.")
        elif not re.fullmatch(r"[A-Za-z]+", first_name):
            errors.append("First name must contain only letters.")

        if last_name and not re.fullmatch(NAME_REGEX, last_name):
            errors.append("Last name must contain only letters and spaces.")

        if phone:
            if not re.fullmatch(r"[6-9]\d{9}", phone):
                errors.append("Enter a valid 10-digit mobile number.")
            elif len(set(phone)) == 1:
                errors.append(
                    "Mobile number cannot contain all identical digits."
                )

        if errors:
            for err in errors:
                messages.error(request, err)

            return render(request, "account_profile.html", _profile_referral_context(request, user))



        user.first_name = first_name.capitalize()
        user.last_name = last_name
        user.phone_number = phone

        photo_updated = False
        previous_profile_pic = user.profile_pic


        if remove_photo == "true":

            if user.profile_pic:
                user.profile_pic = None
                photo_updated = True

            else:
                messages.warning(request,"No profile photo to remove.")

        elif cropped_photo and cropped_photo.startswith("data:image"):

            try:
                image_data = cropped_photo.split(",", 1)[1]
                image_bytes = base64.b64decode(image_data)

                public_id, error = _upload_profile_photo(
                    user,
                    image_bytes
                )

                if error:
                    messages.error(request,"Failed to upload profile photo. Please try again.")

                    return render(request, "account_profile.html", _profile_referral_context(request, user))

                user.profile_pic = public_id
                photo_updated = True

            except Exception:
                messages.error(request,"Invalid profile photo. Please select a valid image and try again.")
                return render(request,"account_profile.html")

        try:
            user.save()
            user.refresh_from_db()

            if remove_photo == "true" and previous_profile_pic:
                _delete_cloudinary_image(previous_profile_pic)

        except Exception as e:
            messages.error(request,"Failed to save profile. Please try again.")
            return render(request,"account_profile.html")

        if remove_photo == "true" and photo_updated:
            messages.success(request,"Profile photo removed successfully.")
        elif photo_updated:
            messages.success(request,"Profile photo updated successfully.")
        else:

            messages.success(request,"Profile updated successfully.")
        return redirect("account_profile")
    referral_code = ReferralCode.objects.filter(user=user, is_active=True).order_by('-created_at').first()
    if referral_code is None:
        referral_code = ReferralCode.objects.create(
            user=user, code=f"REF{_uuid.uuid4().hex[:8].upper()}"
        )
    return render(request,"account_profile.html", {"referral_code": referral_code})


@login_required
@never_cache
def account_address(request):
    addresses = Address.objects.filter(user=request.user)
    return render(request, "account_address.html", {"addresses": addresses})

@login_required
@never_cache
def account_address_add(request):
    if request.method == "POST":
        errors = []
        full_name = request.POST.get("full_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        address_line1 = request.POST.get("address_line1", "").strip()
        address_line2 = request.POST.get("address_line2", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        pincode = request.POST.get("pincode", "").strip()
        country = request.POST.get("country", "India").strip()
        is_default = request.POST.get("is_default") == "on"

        
        if not full_name:
            errors.append("Full name is required.")
        if not phone:
            errors.append("Phone number is required.")
        elif not re.fullmatch(r"[6-9]\d{9}", phone):
            errors.append("Enter a valid 10-digit Indian phone number.")
        if not address_line1:
            errors.append("Address line 1 is required.")
        if not city:
            errors.append("City is required.")
        if not state:
            errors.append("State is required.")
        if not pincode:
            errors.append("Pincode is required.")
        elif not re.fullmatch(r"\d{6}", pincode):
            errors.append("Pincode must be 6 digits.")
        
        if Address.objects.filter(user=request.user).count() >= 3:
            errors.append("You can save up to 3 addresses only.")

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, "account_address_form.html", {
                "form_data": request.POST,
                "action": "add"
            })
        
        existing_count = Address.objects.filter(user=request.user).count()
        if existing_count == 0:
            is_default = True

        if is_default:
            Address.objects.filter(user=request.user).update(is_default=False)

        Address.objects.create(
            user=request.user,
            full_name=full_name,
            phone=phone,
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            state=state,
            pincode=pincode,
            country=country,
            is_default=is_default,
        )

        messages.success(request, "Address added successfully.")
        return redirect("account_address")

    return render(request, "account_address_form.html", {
        "action": "add",
    })

@login_required
@never_cache
def account_address_edit(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)

    if request.method == "POST":
        errors = []
        full_name = request.POST.get("full_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        address_line1 = request.POST.get("address_line1", "").strip()
        address_line2 = request.POST.get("address_line2", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        pincode = request.POST.get("pincode", "").strip()
        country = request.POST.get("country", "India").strip()
        is_default = request.POST.get("is_default") == "on"

        if not full_name:
            errors.append("Full name is required.")
        if not phone:
            errors.append("Phone number is required.")
        elif not re.fullmatch(r"[6-9]\d{9}", phone):
            errors.append("Enter a valid 10-digit Indian phone number.")
        if not address_line1:
            errors.append("Address line 1 is required.")
        if not city:
            errors.append("City is required.")
        if not state:
            errors.append("State is required.")
        if not pincode:
            errors.append("Pincode is required.")
        elif not re.fullmatch(r"\d{6}", pincode):
            errors.append("Pincode must be 6 digits.")

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, "account_address_form.html", {
                "address": address,
                "action": "edit"
            })
        
        if is_default:
            Address.objects.filter(user=request.user).exclude(pk=pk).update(is_default=False)

        address.full_name = full_name
        address.phone = phone
        address.address_line1 = address_line1
        address.address_line2 = address_line2
        address.city = city
        address.state = state
        address.pincode = pincode
        address.country = country
        address.is_default = is_default
        address.save()
        
        messages.success(request, "Address updated successfully.")
        return redirect("account_address")

    return render(request, "account_address_form.html", {
        "address": address,
        "action": "edit"
    })

@login_required
@require_POST
def account_address_delete(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    address.delete()
    messages.success(request, "Address deleted successfully.")
    return redirect("account_address")

@login_required
@require_POST
def account_address_set_default(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    Address.objects.filter(user=request.user).exclude(pk=pk).update(is_default=False)
    address.is_default = True
    address.save()
    messages.success(request, "Default address updated.")
    return redirect("account_address")

@login_required
def account_change_email(request):
    is_google = _is_google_user(request.user)

    if request.method == 'POST':
        if is_google:
            messages.error(request, 'Google account users cannot change their email here.')
            return redirect('account_change_email')

        new_email = request.POST.get('new_email', '').strip().lower()
        password = request.POST.get('password', '')

        if not request.user.check_password(password):
            messages.error(request, 'The password you entered is incorrect.')
            return render(request, 'account_change_email.html', {'is_google_user': is_google})

        if not new_email or '@' not in new_email:
            messages.error(request, 'Please enter a valid email address.')
            return render(request, 'account_change_email.html', {'is_google_user': is_google})

        if new_email == request.user.email.lower():
            messages.error(request, 'New email must differ from your current email.')
            return render(request, 'account_change_email.html', {'is_google_user': is_google})

        if User.objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists():
            messages.error(request, 'This email address is already registered.')
            return render(request, 'account_change_email.html', {'is_google_user': is_google})

        otp = _generate_otp()
        request.session['email_change_otp'] = otp
        request.session['email_change_new_email'] = new_email
        request.session['email_change_otp_time'] = timezone.now().isoformat()

        try:
            _send_email_otp(new_email, otp)
            messages.success(request, 'Verification code sent to your new email.')
        except Exception:
            messages.error(request, 'Failed to send verification code. Please try again.')
            return render(request, 'account_change_email.html', {'is_google_user': is_google})

        return redirect('account_verify_email_otp')

    return render(request, 'account_change_email.html', {'is_google_user': is_google})

@login_required
def account_verify_email_otp(request):
    is_google = _is_google_user(request.user)
    if is_google:
        return redirect('account_profile')

    new_email = request.session.get('email_change_new_email')
    if not new_email:
        messages.error(request, 'Session expired. Please start again.')
        return redirect('account_change_email')

    if request.method == 'POST':
        entered_otp = request.POST.get('otp', '').strip()
        stored_otp = request.session.get('email_change_otp')
        otp_time_str = request.session.get('email_change_otp_time')

        if not stored_otp or not otp_time_str:
            messages.error(request, 'OTP expired. Please request a new one.')
            return redirect('account_change_email')

        otp_time = datetime.fromisoformat(otp_time_str)
        if timezone.is_naive(otp_time):
            otp_time = timezone.make_aware(otp_time)

        if timezone.now() - otp_time > timedelta(minutes=10):
            for key in ['email_change_otp', 'email_change_new_email', 'email_change_otp_time']:
                request.session.pop(key, None)
            messages.error(request, 'OTP has expired. Please request a new one.')
            return redirect('account_change_email')

        if entered_otp != stored_otp:
            messages.error(request, 'Incorrect OTP. Please try again.')
            return render(request, 'verify_email_otp.html', {'new_email': new_email})

        request.user.email = new_email
        request.user.username = new_email
        request.user.save()

        for key in ['email_change_otp', 'email_change_new_email', 'email_change_otp_time']:
            request.session.pop(key, None)

        messages.success(request, 'Your email address has been updated successfully.')
        return redirect('account_profile')

    return render(request, 'verify_email_otp.html', {'new_email': new_email})

@login_required
@require_POST
def account_change_email_resend(request):
    new_email = request.session.get('email_change_new_email')
    if not new_email:
        return JsonResponse({
            'success': False,
            'message': 'Session expired. Please start again.'
        })

    otp = _generate_otp()
    request.session['email_change_otp'] = otp
    request.session['email_change_otp_time'] = timezone.now().isoformat()

    try:
        _send_email_otp(new_email, otp)
        return JsonResponse({
            'success': True,
            'message': 'A new verification code has been sent.'
        })
    except Exception:
        return JsonResponse({
            'success': False,
            'message': 'Failed to send code. Please try again.'
        })

@login_required
def account_change_password(request):
    is_google = _is_google_user(request.user)
    has_local_pw = request.user.has_usable_password()

    if not has_local_pw:
        return render(request, 'change_password.html', {
            'is_google_user': True,
            'errors': {}
        })

    if request.method == 'POST':
        if is_google:
            messages.error(request, 'Google account users cannot change password here.')
            return redirect('account_change_password')

        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        errors = {}

        if not current_password:
            errors['current_password'] = 'Current password is required.'
        elif not request.user.check_password(current_password):
            errors['current_password'] = 'Current password is incorrect.'

        if len(new_password) < 8:
            errors['new_password'] = 'Password must be at least 8 characters.'
        elif new_password == current_password:
            errors['new_password'] = 'New password must differ from your current password.'

        if new_password != confirm_password:
            errors['confirm_password'] = 'Passwords do not match.'

        if errors:
            return render(request, 'change_password.html', {
                'is_google_user': is_google,
                'errors': errors
            })

        request.user.set_password(new_password)
        request.user.save()
        update_session_auth_hash(request, request.user)

        messages.success(request, 'Your password has been updated successfully.')
        return redirect('account_profile')

    return render(request, 'change_password.html', {
        'is_google_user': is_google,
        'errors': {}
    })