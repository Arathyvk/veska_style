from django.db import models
from django.conf import settings


class Address(models.Model):
    ADDRESS_TYPE = [
        ('home',  'Home'),
        ('work',  'Work'),
        ('other', 'Other'),
    ]
 
    user          = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='addresses')
    full_name     = models.CharField(max_length=100)
    phone         = models.CharField(max_length=20)
    address_line1 = models.CharField(max_length=200)
    address_line2 = models.CharField(max_length=200, blank=True)
    city          = models.CharField(max_length=100)
    state         = models.CharField(max_length=100)
    pincode       = models.CharField(max_length=10)
    country       = models.CharField(max_length=100, default='India')
    address_type  = models.CharField(max_length=10, choices=ADDRESS_TYPE, default='home')
    is_default    = models.BooleanField(default=False)
    created_at    = models.DateTimeField(auto_now_add=True) 
 
    class Meta:
        ordering            = ['-is_default', '-created_at']
        verbose_name_plural = "Addresses"
 
    def __str__(self):
        return f"{self.full_name} — {self.city}, {self.pincode}"
 
    def save(self, *args, **kwargs):
        if self.is_default:
            Address.objects.filter(
                user=self.user, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
