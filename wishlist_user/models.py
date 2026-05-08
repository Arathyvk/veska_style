from django.db import models
from product_admin.models import Product
from django.contrib.auth import get_user_model


User = get_user_model()

class Wishlist(models.Model):
    user       = models.ForeignKey(User,on_delete=models.CASCADE, null=True, blank=True)
    products   = models.ManyToManyField(Product, blank=True, related_name='wishlists')
    created_at = models.DateTimeField(auto_now_add=True)
 
    def __str__(self):
        return f"Wishlist[{self.user}]"