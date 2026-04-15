import uuid, datetime
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone


class Coupon(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ('percent', 'Percentage (%)'),
        ('flat',    'Fixed Amount (₹)'),
    ]
    APPLY_TO_CHOICES = [
        ('all',      'All Products'),
        ('category', 'Specific Categories'),
        ('product',  'Specific Products'),
    ]

    code        = models.CharField(max_length=50, unique=True, db_index=True)
    description = models.CharField(max_length=255, blank=True)

    discount_type = models.CharField(max_length=10, choices=DISCOUNT_TYPE_CHOICES)
    value         = models.DecimalField(max_digits=10, decimal_places=2)
    max_discount  = models.DecimalField(max_digits=10, decimal_places=2,
                                        null=True, blank=True,
                                        help_text="Cap for % coupons. Leave blank = no cap.")

    min_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    apply_to   = models.CharField(max_length=10, choices=APPLY_TO_CHOICES, default='all')
    categories = models.JSONField(default=list, blank=True)
    products   = models.ManyToManyField('product_admin.Product', blank=True)

    is_active   = models.BooleanField(default=True)
    valid_from  = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)

    usage_limit    = models.PositiveIntegerField(null=True, blank=True)
    per_user_limit = models.PositiveIntegerField(default=1)
    times_used     = models.PositiveIntegerField(default=0, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.code} ({self.get_discount_type_display()})"


    def check_valid(self):
        now = timezone.now()
        if not self.is_active:
            return False, 'This coupon is currently inactive.'
        if now < self.valid_from:
            return False, 'This coupon is not valid yet.'
        if self.valid_until and now > self.valid_until:
            return False, 'This coupon has expired.'
        if self.usage_limit is not None and self.times_used >= self.usage_limit:
            return False, 'This coupon has reached its usage limit.'
        return True, ''

    def check_user_limit(self, user):
        if not user or not user.is_authenticated:
            return True, ''
        used = CouponUsage.objects.filter(coupon=self, user=user).count()
        if used >= self.per_user_limit:
            return False, f'You have already used this coupon {used} time(s).'
        return True, ''

    def check_min_order(self, subtotal: Decimal):
        if subtotal < self.min_order_value:
            return False, f'Minimum order of ₹{self.min_order_value:.0f} required.'
        return True, ''

    def check_applicability(self, cart_items):
        if self.apply_to == 'all':
            return True, ''
        eligible = self._eligible_items(cart_items)
        if not eligible:
            if self.apply_to == 'category':
                return False, f'Coupon only applies to: {", ".join(self.categories)}.'
            return False, 'Coupon does not apply to items in your cart.'
        return True, ''

    def _eligible_items(self, cart_items):
        if self.apply_to == 'all':
            return cart_items
        if self.apply_to == 'category':
            return [i for i in cart_items if i.product.category in self.categories]
        if self.apply_to == 'product':
            ids = list(self.products.values_list('id', flat=True))
            return [i for i in cart_items if i.product_id in ids]
        return []

    def calculate_discount(self, subtotal: Decimal, cart_items=None) -> Decimal:
        if cart_items and self.apply_to != 'all':
            eligible = self._eligible_items(cart_items)
            base = Decimal(str(sum(float(i.line_total) for i in eligible)))
        else:
            base = subtotal
        if base <= 0:
            return Decimal('0')
        if self.discount_type == 'flat':
            discount = min(self.value, base)
        else:
            discount = (base * self.value / Decimal('100')).quantize(Decimal('0.01'))
            if self.max_discount:
                discount = min(discount, self.max_discount)
        return min(discount, subtotal)

    def validate_all(self, subtotal: Decimal, cart_items, user):
        for fn, args in [
            (self.check_valid,          []),
            (self.check_min_order,      [subtotal]),
            (self.check_user_limit,     [user]),
            (self.check_applicability,  [cart_items]),
        ]:
            ok, reason = fn(*args)
            if not ok:
                return False, Decimal('0'), reason
        return True, self.calculate_discount(subtotal, cart_items), ''


class CouponUsage(models.Model):
    coupon  = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='usages')
    user    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='coupon_usages')
    order   = models.ForeignKey('order_user.Order', on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='coupon_usages')
    used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-used_at']

    def __str__(self):
        return f"{self.user} used {self.coupon.code}"