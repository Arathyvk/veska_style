from decimal import Decimal
from django.db import models
from django.conf import settings


class Wallet(models.Model):
    user      = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet'
    )
    balance    = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Wallet'
        verbose_name_plural = 'Wallets'

    def __str__(self):
        return f"{self.user.email}'s Wallet — ₹{self.balance}"

    @classmethod
    def get_or_create_for(cls, user):
        wallet, _ = cls.objects.get_or_create(user=user)
        return wallet

    def credit(self, amount, reason, order=None, description=''):
        amount = Decimal(str(amount))
        if amount <= 0:
            return None
        self.balance += amount
        self.save(update_fields=['balance', 'updated_at'])
        return WalletTransaction.objects.create(
            wallet           = self,
            transaction_type = 'CREDIT',
            amount           = amount,
            reason           = reason,
            order            = order,
            description      = description,
        )

    def debit(self, amount, reason, order=None, description=''):
        amount = Decimal(str(amount))
        if amount <= 0 or amount > self.balance:
            return None
        self.balance -= amount
        self.save(update_fields=['balance', 'updated_at'])
        return WalletTransaction.objects.create(
            wallet           = self,
            transaction_type = 'DEBIT',
            amount           = amount,
            reason           = reason,
            order            = order,
            description      = description,
        )


class WalletTransaction(models.Model):
    CREDIT = 'CREDIT'
    DEBIT = 'DEBIT'

    TRANSACTION_TYPES = [
        (CREDIT, 'Credit'),
        (DEBIT, 'Debit'),
    ]

    REASON_CHOICES = [
        ('ORDER_CANCEL',  'Order Cancelled'),
        ('ORDER_RETURN',  'Order Returned'),
        ('ORDER_PAYMENT', 'Wallet Payment'),
        ('ADMIN_CREDIT',  'Admin Credit'),
        ('ADMIN_DEBIT',   'Admin Debit'),
        ('REFERRAL',      'Referral Bonus'),      
        ('WELCOME',       'Welcome Bonus'),      
        ('MANUAL',        'Manual'),
    ]

    REASON_REFERRAL     = 'REFERRAL'
    REASON_WELCOME      = 'WELCOME'
    REASON_CANCELLATION = 'ORDER_CANCEL'
    REASON_RETURN       = 'ORDER_RETURN'
    REASON_ORDER_CANCEL = 'ORDER_CANCEL'
    REASON_ORDER_RETURN = 'ORDER_RETURN'
    REASON_ORDER        = 'ORDER_PAYMENT'
    REASON_PAYMENT      = 'ORDER_PAYMENT'
    REASON_ADMIN_CREDIT = 'ADMIN_CREDIT'
    REASON_ADMIN_DEBIT  = 'ADMIN_DEBIT'

    wallet           = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount           = models.DecimalField(max_digits=12, decimal_places=2)
    description      = models.CharField(max_length=300, blank=True)
    reason           = models.CharField(max_length=20, choices=REASON_CHOICES, default='MANUAL')
    order            = models.ForeignKey('order_user.Order', on_delete=models.SET_NULL,null=True, blank=True, related_name='wallet_transactions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'Wallet Transaction'
        verbose_name_plural = 'Wallet Transactions'

    def __str__(self):
        return f"{self.get_transaction_type_display()} ₹{self.amount} ({self.wallet.user.email})"

    @property
    def is_credit(self):
        return self.transaction_type == 'CREDIT'