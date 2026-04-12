from django.db import models
from django.conf import settings
from product_admin.models import Product


class Wishlist(models.Model):
    user       = models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='wishlist')
    products   = models.ManyToManyField(Product, blank=True, related_name='wishlists')
    created_at = models.DateTimeField(auto_now_add=True)
 
    def __str__(self):
        return f"Wishlist[{self.user}]"