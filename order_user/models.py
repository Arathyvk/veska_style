import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone




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
        ('pending',    'Pending'),
        ('confirmed',  'Confirmed'),
        ('processing', 'Processing'),
        ('shipped',    'Shipped'),
        ('delivered',  'Delivered'),
        ('cancelled',  'Cancelled'),
        ('return_requested', 'Return Requested'),
        ('returned',   'Returned'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('cod', 'Cash on Delivery'),
    ]

    order_number    = models.CharField(max_length=30, unique=True,default=_order_number, editable=False, db_index=True)
    user            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,null=True, blank=True, related_name='orders')

    full_name       = models.CharField(max_length=200)
    phone           = models.CharField(max_length=20)
    address_line1   = models.CharField(max_length=255)
    address_line2   = models.CharField(max_length=255, blank=True)
    city            = models.CharField(max_length=100)
    state           = models.CharField(max_length=100)
    pincode         = models.CharField(max_length=10)
    country         = models.CharField(max_length=100, default='India')

    subtotal        = models.DecimalField(max_digits=12, decimal_places=2)
    coupon_code     = models.CharField(max_length=50, blank=True)
    discount_type   = models.CharField(max_length=10, blank=True)
    discount_value  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_charge = models.DecimalField(max_digits=8,  decimal_places=2, default=0)
    tax             = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total           = models.DecimalField(max_digits=12, decimal_places=2)

    payment_method  = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='cod')
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes           = models.TextField(blank=True)

    cancel_reason   = models.TextField(blank=True)
    cancelled_at    = models.DateTimeField(null=True, blank=True)
    return_reason   = models.TextField(blank=True)
    return_requested_at = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Order'

    def __str__(self):
        return f'{self.order_number}'

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

    @property
    def status_color(self):
        return {
            'pending':          'warning',
            'confirmed':        'info',
            'processing':       'info',
            'shipped':          'primary',
            'delivered':        'success',
            'cancelled':        'danger',
            'return_requested': 'warning',
            'returned':         'secondary',
        }.get(self.status, 'secondary')

    @property
    def status_steps(self):
        base = ['confirmed', 'processing', 'shipped', 'delivered']
        return base



class OrderItem(models.Model):
    ITEM_STATUS_CHOICES = [
        ('active',    'Active'),
        ('cancelled', 'Cancelled'),
    ]

    order        = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product      = models.ForeignKey('product_admin.Product', on_delete=models.SET_NULL, null=True, blank=True)
    product_name = models.CharField(max_length=255)
    product_slug = models.SlugField(max_length=255, blank=True)
    size         = models.CharField(max_length=50, blank=True)
    image_url    = models.CharField(max_length=500, blank=True)
    unit_price   = models.DecimalField(max_digits=10, decimal_places=2)
    quantity     = models.PositiveIntegerField()
    line_total   = models.DecimalField(max_digits=12, decimal_places=2)

    status        = models.CharField(max_length=20, choices=ITEM_STATUS_CHOICES, default='active')
    cancel_reason = models.TextField(blank=True)
    cancelled_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Order item'

    def __str__(self):
        return f'{self.quantity}× {self.product_name}'

    @property
    def can_cancel(self):
        return (
            self.status == 'active' and
            self.order.status in ('pending', 'confirmed', 'processing')
        )