from django.db import models
from django.conf import settings
from product_admin.models import Product, ProductVariant
from users.models import User  



MAX_QTY_PER_ITEM = 10  


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('placed', 'Placed'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    session_key = models.CharField(max_length=40, blank=True, null=True)

    full_name       = models.CharField(max_length=255)
    phone           = models.CharField(max_length=20)
    address_line1   = models.CharField(max_length=255)
    address_line2   = models.CharField(max_length=255, blank=True, null=True)
    city            = models.CharField(max_length=100)
    state           = models.CharField(max_length=100)
    pincode         = models.CharField(max_length=20)
    country         = models.CharField(max_length=100)

    subtotal        = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_charge = models.DecimalField(max_digits=10, decimal_places=2)
    tax             = models.DecimalField(max_digits=10, decimal_places=2)
    total           = models.DecimalField(max_digits=10, decimal_places=2)

    payment_method  = models.CharField(max_length=50)
    status          = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    notes           = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.user:
            return f"Order #{self.id} - {self.user.email}"
        return f"Order #{self.id} - Guest ({self.session_key})"


class OrderItem(models.Model):
    order    = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product  = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant  = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField()
    price    = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.product.name} × {self.quantity}"

    @property
    def line_total(self):
        return self.price * self.quantity
    

class Checkout(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
