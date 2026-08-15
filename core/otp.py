import random
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

OTP_EXPIRY_MINUTES = 2
MAX_OTP_ATTEMPTS = 3

def gen_otp():
    return str(random.randint(1000, 9999))

def send_otp_email(email, otp, subject="Veska — Verify your email"):
    send_mail(
        subject=subject,
        message=(
            "Hello,\n\n"
            "Welcome to Veska!\n\n"
            "Thank you for choosing Veska. To complete your email verification, "
            "please use the One-Time Password (OTP) below:\n\n"
            f"Verification Code: {otp}\n\n"
            f"This code is valid for {OTP_EXPIRY_MINUTES} minutes.\n\n"
            "If you did not request this verification, you can safely ignore this email.\n"
            "Please do not share this OTP with anyone for security reasons.\n\n"
            "If you need any assistance, feel free to contact our support team.\n\n"
            "Warm regards,\n"
            "support@veska.in"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )
def is_otp_expired(otp_time_str):
    if not otp_time_str:
        return True
    try:
        otp_time = timezone.datetime.fromisoformat(otp_time_str)
        if timezone.is_naive(otp_time):
            otp_time = timezone.make_aware(otp_time)
        return timezone.now() > otp_time + timedelta(minutes=OTP_EXPIRY_MINUTES)
    except:
        return True

def save_otp_to_session(request, purpose, otp):
    request.session[f"{purpose}_otp"] = otp
    request.session[f"{purpose}_otp_time"] = timezone.now().isoformat()
    request.session[f"{purpose}_otp_attempts"] = 0  
    request.session.modified = True
    request.session.save()

def get_otp_from_session(request, purpose):
    return (
        request.session.get(f"{purpose}_otp"),
        request.session.get(f"{purpose}_otp_time"),
    )

def clear_otp_from_session(request, purpose):
    request.session.pop(f"{purpose}_otp", None)
    request.session.pop(f"{purpose}_otp_time", None)
    request.session.pop(f"{purpose}_otp_attempts", None)

def is_otp_attempts_exceeded(request, purpose):
    attempts = request.session.get(f"{purpose}_otp_attempts", 0)
    return attempts >= MAX_OTP_ATTEMPTS

def increment_otp_attempts(request, purpose):
    attempts = request.session.get(f"{purpose}_otp_attempts", 0) + 1
    request.session[f"{purpose}_otp_attempts"] = attempts
    request.session.modified = True
    request.session.save()
    return attempts

def reset_otp_attempts(request, purpose):
    request.session[f"{purpose}_otp_attempts"] = 0
    request.session.modified = True
    request.session.save()