from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.auth import get_user_model

MAX_QTY_PER_ITEM = 10

User = get_user_model()

class Cart(models.Model):
    user        = models.ForeignKey(User,on_delete=models.CASCADE,null=True, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cart'

    def __str__(self):
        return f'Cart of {self.user}'

    @property
    def total_items(self):
        return sum(i.quantity for i in self.items.all())

    @property
    def subtotal(self):
        return sum(i.line_total for i in self.items.all())

    @property
    def is_empty(self):
        return not self.items.exists()

    def get_active_items(self):
        return self.items.select_related('product', 'variant').filter(
            product__is_active=True
        )
    

class CartItem(models.Model):
    cart     = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product  = models.ForeignKey('product_admin.Product',        on_delete=models.CASCADE)
    variant  = models.ForeignKey('product_admin.ProductVariant', on_delete=models.SET_NULL,null=True, blank=True)
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
        return self.product.total_stock

    @property
    def is_in_stock(self):
        return self.available_stock > 0

    @property
    def is_available(self):
        return self.product.is_active and self.is_in_stock

    @property
    def unit_price(self):
        if self.variant and self.variant.price is not None:
            return self.variant.price
        return self.product.price

    @property
    def display_image(self):
        if self.variant:
            img = self.variant.images.first()
            if img:
                return img
        for v in self.product.variants.all():
            img = v.images.first()
            if img:
                return img
        return None

    @property
    def line_total(self):
        return self.unit_price * min(self.quantity, self.available_stock)

    @property
    def active_offer(self):
        from offer_admin.views import get_applicable_offers

        user = None
        if self.cart and self.cart.user and self.cart.user.is_authenticated:
            user = self.cart.user

        best_offer = None
        best_discount = Decimal('0')
        line_total = self.unit_price * self.quantity

        for offer in get_applicable_offers(self.product, user):
            discount = offer.calculate_discount(line_total)
            if discount > best_discount:
                best_offer = offer
                best_discount = discount

        return best_offer

    @property
    def discounted_unit_price(self):
        offer = self.active_offer
        if offer:
            return self.unit_price - (offer.calculate_discount(self.unit_price * self.quantity) / self.quantity)
        return self.unit_price

    @property
    def discounted_line_total(self):
        offer = self.active_offer
        line = self.unit_price * min(self.quantity, self.available_stock)
        if offer:
            return line - offer.calculate_discount(line)
        return line

    @property
    def max_allowed(self):
        return min(self.available_stock, MAX_QTY_PER_ITEM)