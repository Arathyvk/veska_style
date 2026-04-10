from django.db import models
from product_admin.models import Product, ProductVariant
from django.conf import settings

MAX_QTY_PER_ITEM = 10  



class Cart(models.Model):
    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart [{self.session_key}]"

    @property
    def items(self):
        return self.cart_items.select_related('product', 'variant')

    @property
    def total_items(self):
        return self.cart_items.aggregate(
            total=models.Sum('quantity')
        )['total'] or 0

    @property
    def subtotal(self):
        return sum(item.line_total for item in self.items)

    @property
    def is_empty(self):
        return not self.cart_items.exists()

    def get_or_create_item(self, product, variant=None, qty=1):
        item, created = CartItem.objects.get_or_create(
            cart=self,
            product=product,
            variant=variant,
            defaults={'quantity': 0},
        )

        available = variant.stock if variant else product.total_stock
        new_qty = min(item.quantity + qty, available, MAX_QTY_PER_ITEM)

        item.quantity = new_qty
        item.save()
        return item, created


class CartItem(models.Model):
    cart     = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='cart_items')
    product  = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant  = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('cart', 'product', 'variant')
        ordering = ['added_at']

    def __str__(self):
        size = f" ({self.variant.size})" if self.variant else ""
        return f"{self.product.name}{size} × {self.quantity}"

    @property
    def unit_price(self):
        return self.product.price

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    @property
    def available_stock(self):
        return self.variant.stock if self.variant else self.product.total_stock

    @property
    def max_qty(self):
        return min(self.available_stock, MAX_QTY_PER_ITEM)

    @property
    def is_available(self):
        return self.product.is_active and self.available_stock > 0



class Wishlist(models.Model):
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    products = models.ManyToManyField(Product, blank=True)

    def __str__(self):
        return f"Wishlist [{self.session_key}]"


