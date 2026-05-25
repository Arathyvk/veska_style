import uuid

from django.db import models
from django.conf import settings
from decimal import Decimal


class Wallet(models.Model):
    user            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name ="wallet")
    balance         = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)


    class Meta:
        verbose_name          = "wallet"
        verbose_name_plural   = 'wallets'

    def __Str__(self):
        return f"{self.user.username}'s Wallet ₹{self.balance}"    
    
    
    def credit(self, amount, reason='', order=None, reference='', description=''):

        amount = Decimal(str(amount))

        self.balance += amount
        self.save(update_fields=['balance', 'updated_at'])

        WalletTransaction.objects.create(
            wallet=self,
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
 
    REASON_CANCELLATION = 'order_cancellation'
    REASON_RETURN       = 'order_return'
    REASON_PAYMENT      = 'order_payment'
    REASON_MANUAL       = 'manual_adjustment'
    REASON_REFUND       = 'refund'
 
    REASON_CHOICES = [
        (REASON_CANCELLATION, 'Order Cancellation Refund'),
        (REASON_RETURN,       'Order Return Refund'),
        (REASON_PAYMENT,      'Order Payment'),
        (REASON_MANUAL,       'Manual Adjustment'),
        (REASON_REFUND,       'Refund'),
    ]
 
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
        return (
            f"{self.get_transaction_type_display()} ₹{self.amount} "
            f"({self.wallet.user.username}) — {self.get_reason_display()}"
        )
 

    @property
    def is_credit(self):
        return self.transaction_type == self.CREDIT
    

    @property
    def is_debit(self):
        return self.transaction_type == self.DEBIT
    
 