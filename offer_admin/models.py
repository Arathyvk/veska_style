from django.db import models
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from product_admin.models import Product
from category_admin.models import Category

class BaseOffer(models.Model):
    OFFER_TYPES = [
        ('PRODUCT', 'Product Offer'),
        ('CATEGORY', 'Category Offer'),
        ('REFERRAL', 'Referral Offer'),
    ]
    
    DISCOUNT_TYPES = [
        ('PERCENTAGE', 'Percentage (%)'),
        ('FIXED', 'Fixed Amount (₹)'),
    ]
    
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=200)
    offer_type = models.CharField(max_length=20, choices=OFFER_TYPES)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPES, default='PERCENTAGE')
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    
    products = models.ManyToManyField(Product, blank=True, related_name='offers')
    categories = models.ManyToManyField(Category, blank=True, related_name='offers')
    
    referral_code = models.CharField(max_length=50, unique=True, null=True, blank=True)
    referral_reward_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    referred_user_reward = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    
    min_purchase_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_discount_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    usage_limit = models.PositiveIntegerField(default=0, help_text="0 = unlimited")
    used_count = models.PositiveIntegerField(default=0)
    per_user_limit = models.PositiveIntegerField(default=1)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    
    class Meta:
        ordering = ['-created_at']

    
    def __str__(self):
        return f"{self.name} ({self.get_offer_type_display()})"
    
    
    @property
    def is_valid(self):
        now = timezone.now()
        return (self.is_active and 
                self.start_date <= now <= self.end_date and
                (self.usage_limit == 0 or self.used_count < self.usage_limit))
    

    @property
    def discount_display(self):
        if self.discount_type == 'PERCENTAGE':
            return f"{self.discount_value}% OFF"
        return f"₹{self.discount_value} OFF"
    

    def calculate_discount(self, amount):
        if not self.is_valid:
            return 0
        
        if self.min_purchase_amount and amount < self.min_purchase_amount:
            return 0
        
        if self.discount_type == 'PERCENTAGE':
            discount = (amount * self.discount_value) / 100
        else:
            discount = self.discount_value
        
        if self.max_discount_amount:
            discount = min(discount, self.max_discount_amount)
        
        return min(discount, amount)


class UserOfferUsage(models.Model):
    user    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='offer_usage')
    offer = models.ForeignKey(BaseOffer, on_delete=models.CASCADE, related_name='user_usage')
    usage_count = models.PositiveIntegerField(default=0)
    last_used = models.DateTimeField(null=True, blank=True)
    

    class Meta:
        unique_together = ['user', 'offer']
    

    def can_use(self):
        return self.usage_count < self.offer.per_user_limit


class ReferralCode(models.Model):
    
    user    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='referral_codes')
    code = models.CharField(max_length=50, unique=True)
    total_referrals = models.PositiveIntegerField(default=0)
    total_earnings = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    

    def __str__(self):
        return f"{self.user.email} - {self.code}"


class ReferralTransaction(models.Model):
    
    referrer = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='referral_transactions')
    referred_user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='referred_by_transactions')
    referral_code = models.ForeignKey(ReferralCode, on_delete=models.CASCADE)
    amount_earned = models.DecimalField(max_digits=10, decimal_places=2)
    order_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    is_credited = models.BooleanField(default=False)
    
    
    def __str__(self):
        return f"{self.referrer.email} referred {self.referred_user.email}"