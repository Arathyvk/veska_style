import uuid
import datetime
from django.db import models
from django.conf import settings
from product_admin.models import Product, ProductVariant
from django.contrib.auth import get_user_model

User = get_user_model()


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending',          'Pending'),
        ('confirmed',        'Confirmed'),
        ('processing',       'Processing'),
        ('shipped',          'Shipped'),
        ('delivered',        'Delivered'),
        ('cancelled',        'Cancelled'),
        ('return_requested', 'Return Requested'),
        ('returned',         'Returned'),
    ]
    PAYMENT_CHOICES = [
        ('cod', 'Cash on Delivery'),
    ]
    CANCEL_REASON_CHOICES = [
        ('changed_mind',  'Changed my mind'),
        ('wrong_item',    'Ordered wrong item'),
        ('found_cheaper', 'Found a better price'),
        ('delay',         'Delivery taking too long'),
        ('other',         'Other'),
    ]
    RETURN_REASON_CHOICES = [
        ('defective',        'Product is defective'),
        ('wrong_item',       'Wrong item received'),
        ('not_as_described', 'Not as described'),
        ('damaged',          'Damaged during delivery'),
        ('other',            'Other'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,      
        blank=True
    )    
    session_key = models.CharField(max_length=40, blank=True, db_index=True)

    order_number = models.CharField(max_length=24, unique=True, editable=False)

    full_name     = models.CharField(max_length=255)
    phone         = models.CharField(max_length=20)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    city          = models.CharField(max_length=100)
    state         = models.CharField(max_length=100)
    pincode       = models.CharField(max_length=20)
    country       = models.CharField(max_length=100, default='India')

    subtotal        = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount        = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax             = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total           = models.DecimalField(max_digits=10, decimal_places=2)

    payment_method = models.CharField(max_length=50, choices=PAYMENT_CHOICES, default='cod')
    status         = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    notes          = models.TextField(blank=True)

    cancel_reason       = models.CharField(max_length=30, choices=CANCEL_REASON_CHOICES, blank=True)
    cancel_reason_other = models.TextField(blank=True)
    cancelled_at        = models.DateTimeField(null=True, blank=True)

    return_reason       = models.CharField(max_length=30, choices=RETURN_REASON_CHOICES, blank=True)
    return_reason_other = models.TextField(blank=True)
    return_requested_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.order_number}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            prefix = datetime.datetime.now().strftime('%y%m%d')
            self.order_number = f"VSK{prefix}{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    @property
    def address_one_line(self):
        parts = [self.address_line1]
        if self.address_line2:
            parts.append(self.address_line2)
        parts += [self.city, self.state, self.pincode, self.country]
        return ', '.join(parts)

    @property
    def can_cancel(self):
        return self.status in ('pending', 'confirmed', 'processing')

    @property
    def can_return(self):
        return self.status == 'delivered'


class OrderItem(models.Model):
    order        = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')

    product      = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    product_name = models.CharField(max_length=255)
    product_slug = models.SlugField(max_length=300, blank=True)
    size         = models.CharField(max_length=50, blank=True)
    image_url    = models.URLField(blank=True)

    unit_price   = models.DecimalField(max_digits=10, decimal_places=2)
    quantity     = models.PositiveIntegerField()
    line_total   = models.DecimalField(max_digits=10, decimal_places=2)

    is_cancelled        = models.BooleanField(default=False)
    cancel_reason       = models.CharField(max_length=30, blank=True)
    cancel_reason_other = models.TextField(blank=True)
    cancelled_at        = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"

    def get_cancel_reason_display(self):
        reasons = dict(Order.CANCEL_REASON_CHOICES)
        return reasons.get(self.cancel_reason, self.cancel_reason)