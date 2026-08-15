import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from order_admin.models import RETURN_DAYS


RETURN_REASONS = [
    ('wrong_size',       'Wrong size received'),
    ('wrong_item',       'Wrong item received'),
    ('defective',        'Defective / damaged product'),
    ('not_as_described', 'Not as described'),
    ('changed_mind',     'Changed my mind'),
    ('quality_issue',    'Quality not as expected'),
    ('other',            'Other'),
]


def _order_number():
    date_part   = timezone.now().strftime('%Y%m%d')
    unique_part = uuid.uuid4().hex[:4].upper()
    return f'VES-{date_part}-{unique_part}'


class Coupon(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ('flat',    'Flat Amount Off'),
        ('percent', 'Percentage Off'),
    ]
    code            = models.CharField(max_length=50, unique=True, db_index=True)
    discount_type   = models.CharField(max_length=10, choices=DISCOUNT_TYPE_CHOICES, default='flat')
    value           = models.DecimalField(max_digits=10, decimal_places=2)
    min_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_discount    = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active       = models.BooleanField(default=True)
    valid_from      = models.DateTimeField(default=timezone.now)
    valid_until     = models.DateTimeField(null=True, blank=True)
    usage_limit     = models.PositiveIntegerField(null=True, blank=True)
    times_used      = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-valid_from']

    def __str__(self):
        return self.code

    def is_valid(self):
        now = timezone.now()
        if not self.is_active:
            return False, 'This coupon is inactive.'
        if self.valid_until and now > self.valid_until:
            return False, 'This coupon has expired.'
        if now < self.valid_from:
            return False, 'This coupon is not yet active.'
        if self.usage_limit is not None and self.times_used >= self.usage_limit:
            return False, 'This coupon has reached its usage limit.'
        return True, ''

    def calculate_discount(self, subtotal: Decimal) -> Decimal:
        if subtotal < self.min_order_value:
            return Decimal('0')
        if self.discount_type == 'flat':
            discount = self.value
        else:
            discount = (subtotal * self.value / Decimal('100')).quantize(Decimal('0.01'))
            if self.max_discount:
                discount = min(discount, self.max_discount)
        return min(discount, subtotal)


class Order(models.Model):

    STATUS_CHOICES = [
        ('pending',          'Pending'),
        ('confirmed',        'Confirmed'),
        ('processing',       'Processing'),
        ('shipped',          'Shipped'),
        ('delivered',        'Delivered'),
        ('cancelled',        'Cancelled'),
        ('refunded',         'Refunded'),
        ('return_requested', 'Return Requested'),
        ('returned',         'Returned'),
    ]

    PAYMENT_STATUS = [
        ('pending',  'Pending'),
        ('paid',     'Paid'),
        ('failed',   'Failed'),
        ('refunded', 'Refunded'),
    ]

    PAYMENT_METHOD = [
        ('stripe',  'Stripe'), 
        ('cod',     'Cash on Delivery'),
        ('wallet',  'Wallet'),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')

    full_name     = models.CharField(max_length=120)
    phone         = models.CharField(max_length=20)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    city          = models.CharField(max_length=80)
    state         = models.CharField(max_length=80)
    pincode       = models.CharField(max_length=20)
    country       = models.CharField(max_length=60)

    subtotal           = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    coupon_code        = models.CharField(max_length=50, blank=True, default='')
    discount_amount    = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_charge    = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    offer_details      = models.CharField(max_length=255, blank=True, null=True)
    offer_discount     = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    wallet_amount_used = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total              = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD, default='stripe')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')
    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    delivered_at          = models.DateTimeField(null=True, blank=True)
    cancelled_at          = models.DateTimeField(null=True, blank=True)
    return_reason         = models.TextField(blank=True, null=True)
    return_notes          = models.TextField(blank=True, null=True)
    return_requested_at   = models.DateTimeField(blank=True, null=True)
    cancel_reason         = models.TextField(blank=True, null=True)

    notes      = models.TextField(blank=True)
    paid_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.order_number} — {self.user.email}"

    @property
    def order_number(self):
        return str(self.uuid).split('-')[0].upper()

    @property
    def can_return(self):
        if self.status != 'delivered':
            return False
        if not self.delivered_at:
            return False
        return_deadline = self.delivered_at + timedelta(days=RETURN_DAYS)
        return timezone.now() <= return_deadline
    
    @property
    def can_cancel(self):
        return self.status in ('pending', 'confirmed', 'processing')
    
    @property
    def return_deadline(self):
        if self.delivered_at:
            return self.delivered_at + timedelta(days=RETURN_DAYS)
        return None

    def get_payment_method_display(self):
        payment_display = {
            'stripe': 'Stripe',
            'cod': 'Cash on Delivery',
            'wallet': 'Wallet'
        }
        return payment_display.get(self.payment_method, self.payment_method)

    def get_status_display(self):
        status_display = dict(self.STATUS_CHOICES)
        return status_display.get(self.status, self.status)

    @property
    def address_one_line(self):
        parts = [self.address_line1]
        if self.address_line2:
            parts.append(self.address_line2)
        parts.extend([self.city, self.state, self.pincode, self.country])
        return ', '.join(filter(None, parts))


class OrderItem(models.Model):

    CANCEL_STATUS_CHOICES = [
        ('none',      'None'),
        ('requested', 'Requested'),
        ('cancelled', 'Cancelled'),
    ]

    order        = models.ForeignKey('order_user.Order', on_delete=models.CASCADE, related_name='items')
    product      = models.ForeignKey('product_admin.Product', on_delete=models.SET_NULL, null=True)
    variant      = models.ForeignKey('product_admin.ProductVariant', on_delete=models.SET_NULL, null=True, blank=True)
    product_name = models.CharField(max_length=255)
    product_slug = models.SlugField(max_length=255)
    brand        = models.CharField(max_length=100, blank=True, default='')
    size         = models.CharField(max_length=20, blank=True)
    color        = models.CharField(max_length=100, blank=True)
    image_url    = models.URLField(blank=True)
    unit_price   = models.DecimalField(max_digits=10, decimal_places=2)
    quantity     = models.PositiveIntegerField()
    
    line_total    = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_cancelled  = models.BooleanField(default=False)
    cancel_status = models.CharField(max_length=20, choices=CANCEL_STATUS_CHOICES, default='none')
    cancel_reason = models.TextField(blank=True)

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"
    
    @property
    def can_cancel(self):
        return (
            self.cancel_status == 'none'
            and self.order.status in ('pending', 'confirmed', 'processing')
        )
    
    @property
    def status(self):
        if self.cancel_status == 'cancelled':
            return 'cancelled'
        return 'active'

    def save(self, *args, **kwargs):
        self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)