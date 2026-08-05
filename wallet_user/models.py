import uuid

from django.db import models
from django.conf import settings
from decimal import Decimal


class Wallet(models.Model):
    user            = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name ="wallet",unique=True)
    balance         = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)


    class Meta:
        verbose_name          = "wallet"
        verbose_name_plural   = 'wallets'

    def __str__(self):
        name = f"{self.user.first_name} {self.user.last_name}".strip()
        if not name:
            name = self.user.email
        return f"{name}'s Wallet ₹{self.balance}"    
    
    
    def credit(self, amount, reason='', order=None, reference='', description=''):

        amount = Decimal(str(amount))

        self.balance += amount
        self.save(update_fields=['balance', 'updated_at'])

        WalletTransaction.objects.create(
            wallet=self,
            user=self.user,
            transaction_type=WalletTransaction.CREDIT,
            amount=amount,
            reason=reason,
            order=order,
            reference=reference or str(uuid.uuid4())[:12].upper(),
            description=description,
        )
 

    def debit(self, amount, reason='', order=None, reference='', description=''):
        amount = Decimal(str(amount))

        if amount > self.balance:
            raise ValueError("Insufficient wallet balance.")

        self.balance -= amount
        self.save(update_fields=['balance', 'updated_at'])

        WalletTransaction.objects.create(
            wallet=self,
            user=self.user,
            transaction_type=WalletTransaction.DEBIT,
            amount=amount,
            reason=reason,
            order=order,
            reference=reference or str(uuid.uuid4())[:12].upper(),
            description=description,
        )



    def can_pay(self, amount):
        return self.balance >= Decimal(str(amount))


    
class WalletTransaction(models.Model):
    CREDIT = 'credit'
    DEBIT  = 'debit'        
 
    TRANSACTION_TYPES = [
        (CREDIT, 'Credit'),
        (DEBIT,  'Debit'),
    ]
 
    REASON_PURCHASE = 'purchase'
    REASON_CANCELLATION = 'cancellation'
    REASON_RETURN = 'return'     
    REASON_REFERRAL = 'referral'
    REASON_MANUAL = 'manual'
    REASON_ORDER = 'order'
    REASON_WELCOME = 'welcome'
    REASON_CHOICES = [
        (REASON_PURCHASE, 'Purchase'),
        (REASON_CANCELLATION, 'Cancellation'),
        (REASON_RETURN, 'Return'),      
        (REASON_REFERRAL, 'Referral'),
        (REASON_MANUAL, 'Manual Adjustment'),
        (REASON_ORDER, 'Order'),
        (REASON_WELCOME, 'Welcome Bonus'),
    ]
    user             = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name ="transaction", null=True, blank=True)
    wallet           = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount           = models.DecimalField(max_digits=12, decimal_places=2)
    description      = models.CharField(max_length=300, blank=True)
    reason           = models.CharField(max_length=20, choices=REASON_CHOICES, default=REASON_MANUAL)
    order            = models.ForeignKey('order_user.Order', on_delete=models.SET_NULL,null=True, blank=True, related_name='wallet_transactions')
    reference        = models.CharField(max_length=50, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
 

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'Wallet Transaction'
        verbose_name_plural = 'Wallet Transactions'
 

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} - {self.get_reason_display()}"
 

    @property
    def is_credit(self):
        return self.transaction_type == self.CREDIT
    

    @property
    def is_debit(self):
        return self.transaction_type == self.DEBIT
    
 