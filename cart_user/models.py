from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator


MAX_QTY_PER_ITEM = 10  


class Cart(models.Model):
    user       = models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cart'

    def __str__(self):
        return f'Cart of {self.user}'


    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.select_related('product', 'variant'))

    @property
    def subtotal(self):
        return sum(item.line_total for item in self.items.select_related('product', 'variant'))

    @property
    def is_empty(self):
        return not self.items.exists()

    def get_active_items(self):
        return self.items.select_related(
            'product', 'variant'
        ).filter(
            product__is_listed=True,
            product__is_blocked=False,
        )

    def has_blocked_items(self):
        return self.items.exclude(
            product__is_listed=True,
            product__is_blocked=False,
        ).exists()


class CartItem(models.Model):
    cart     = models.ForeignKey(Cart,    on_delete=models.CASCADE, related_name='items')
    product  = models.ForeignKey('product_admin.Product',        on_delete=models.CASCADE)
    variant  = models.ForeignKey('product_admin.ProductVariant', on_delete=models.SET_NULL,
                                 null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        unique_together = ('cart', 'product', 'variant')
        verbose_name    = 'Cart item'

    def __str__(self):
        return f'{self.quantity}× {self.product.name}'


    @property
    def available_stock(self):
        if self.variant:
            return self.variant.stock
        return self.product.stock

    @property
    def is_in_stock(self):
        return self.available_stock > 0

    @property
    def is_available(self):
        return (
            self.product.is_listed
            and not self.product.is_blocked
            and self.is_in_stock
        )

    @property
    def effective_qty(self):
        return min(self.quantity, self.available_stock)

    @property
    def unit_price(self):
        if self.variant and self.variant.price is not None:
            return self.variant.price
        return self.product.price

    @property
    def line_total(self):
        return self.unit_price * self.effective_qty

    @property
    def max_allowed(self):
        return min(self.available_stock, MAX_QTY_PER_ITEM)