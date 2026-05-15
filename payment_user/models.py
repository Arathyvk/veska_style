from django.db import models
from django.conf import settings


class RazorpayTransaction(models.Model):
    STATUS_CHOICES = [
        ('creates', 'created'),
        ('paid',    'paid'),
        ('failed',  'failed'),
        ('refunded','refunded'),

    ]

    order               = models.ForeignKey('order_user.Order', on_delete=models.CASCADE,  related_name='razorpay_transactions')
    razorpay_order_id   = models.CharField(max_length=100, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    razorpay_signature  = models.CharField(max_length=300, blank=True)
    amount              = models.DecimalField(max_digits=12, decimal_places=2)
    currency            = models.CharField(max_length=10, default='INR')
    status              = models.CharField(max_length=20, choices=STATUS_CHOICES, default='created')
    failure_reason      = models.TextField(blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)


    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order.order_number} | {self.status} | ₹{self.amount}"
    

class CouponUsage(models.Model):
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    coupon     = models.ForeignKey('coupon_admin.Coupon', on_delete=models.CASCADE)
    order      = models.ForeignKey('order_user.Order', on_delete=models.CASCADE)
    used_at    =models.DateTimeField(auto_now_add=True)


    class Meta:
        unique_together = ('user', 'coupon')

    def __str__(self):
        return f"{self.user.username} used {self.coupon.code}"










        

