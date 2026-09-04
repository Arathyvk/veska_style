import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import F

from offer_admin.models import BaseOffer
from users.models import ReferralCode, ReferralTransaction
from wallet_user.utils import get_or_create_wallet
from wallet_user.models import WalletTransaction

logger = logging.getLogger(__name__)


def get_active_referral_settings():
    return BaseOffer.objects.filter(offer_type='REFERRAL', is_active=True).first()


@transaction.atomic
def credit_referral_bonus(referrer, referred_user, referral_code=None):
    if referrer.uuid == referred_user.uuid:
        return

    settings_obj = get_active_referral_settings()
    if not settings_obj:
        logger.info("Referral program inactive — skipping bonus for %s", referred_user.email)
        return

    already_credited = ReferralTransaction.objects.filter(
        referred_user=referred_user, is_credited=True
    ).exists()
    if already_credited:
        return

    referral_code_obj = referral_code or ReferralCode.objects.filter(
        user=referrer, is_active=True
    ).first()

    txn = ReferralTransaction.objects.create(
        referrer=referrer,
        referred_user=referred_user,
        referral_code=referral_code_obj,
        is_credited=False,
    )

    referrer_wallet = get_or_create_wallet(referrer)
    referrer_wallet.credit(
        amount=settings_obj.referral_reward_amount,
        reason=WalletTransaction.REASON_REFERRAL,
        order=None,
        description=f"Referral bonus for inviting {referred_user.email}",
    )

    if settings_obj.referred_user_reward:
        referred_wallet = get_or_create_wallet(referred_user)
        referred_wallet.credit(
            amount=settings_obj.referred_user_reward,
            reason=WalletTransaction.REASON_WELCOME,
            order=None,
            description="Welcome bonus from referral signup",
        )

    txn.is_credited = True
    txn.amount_earned = settings_obj.referral_reward_amount
    txn.referred_user_bonus = settings_obj.referred_user_reward if settings_obj.referred_user_reward else 0
    txn.save(update_fields=['is_credited', 'amount_earned', 'referred_user_bonus'])

    if referral_code_obj:
        ReferralCode.objects.filter(pk=referral_code_obj.pk).update(
            total_referrals=F('total_referrals') + 1,
            total_earnings=F('total_earnings') + settings_obj.referral_reward_amount,
        )