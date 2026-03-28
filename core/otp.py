import random
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import time

OTP_EXPIRY_MINUTES = 2


def gen_otp():
    return str(random.randint(1000, 9999))


def send_otp_email(email, otp, subject="Veska — Verify your email"):
    send_mail(
        subject=subject,
        message=f"Your OTP is {otp}. Valid for {OTP_EXPIRY_MINUTES} minutes.",
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
    request.session[f"{purpose}_otp"]      = otp
    request.session[f"{purpose}_otp_time"] = timezone.now().isoformat()    
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