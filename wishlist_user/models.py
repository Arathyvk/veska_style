from django.db import models
from django.contrib.auth import get_user_model
from product_admin.models import Product

User = get_user_model()


class Wishlist(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Wishlist[{self.user}]"


class WishlistProduct(models.Model):
    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    color   = models.CharField(max_length=100, blank=True, null=True)
    selected_size = models.CharField(max_length=20, blank=True, null=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('wishlist', 'product', 'selected_size', 'color')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.product.name} ({self.selected_size or 'no size'}) — {self.wishlist.user}"