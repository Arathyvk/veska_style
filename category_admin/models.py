from django.db import models
import uuid

class Category(models.Model):
    uuid        = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name        = models.CharField(max_length=100, unique=True)
    slug        = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    image       = models.ImageField(upload_to='category_images/', blank=True, null=True) 
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def block(self):
        self.is_active = False
        self.save(update_fields=['is_active'])

    def unblock(self):
        self.is_active = True
        self.save(update_fields=['is_active'])