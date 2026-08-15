import uuid
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

from users.models import ReferralCode

logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_referral_code_for_new_user(sender, instance, created, **kwargs):
    if not created:
        return

    if ReferralCode.objects.filter(user=instance).exists():
        return

    code = f"REF{uuid.uuid4().hex[:8].upper()}"
    ReferralCode.objects.create(user=instance, code=code)
    logger.info("Created referral code %s for new user %s", code, instance.email)
