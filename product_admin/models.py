from django.db import models
import uuid
import os
from PIL import Image as PILImage


CATEGORY_CHOICES = [
    ('Formal', 'Formal'),
    ('Casual', 'Casual'),
    ('Party',  'Party'),
    ('Sports', 'Sports'),
    ('Ethnic', 'Ethnic'),
]


class Product(models.Model):
    uuid        = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name        = models.CharField(max_length=255)
    price       = models.DecimalField(max_digits=10, decimal_places=2)
    color       = models.CharField(max_length=100, blank=True)
    category    = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    stock       = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def primary_image(self):
        """Returns the first ProductImage object (lowest order), or None."""
        return self.images.order_by('order').first()

    @property
    def all_images(self):
        return self.images.order_by('order')

    @property
    def total_stock(self):
        variant_total = sum(v.stock for v in self.variants.all())
        return variant_total if variant_total > 0 else self.stock

    def deactivate(self):
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])

    def activate(self):
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])


def product_image_upload_path(instance, filename):
    ext  = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    name = f"{uuid.uuid4().hex[:10]}.{ext}"
    return os.path.join('products', str(instance.product.uuid), name)


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='images'
    )
    image   = models.ImageField(upload_to=product_image_upload_path)
    order   = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.product.name} — image {self.order}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._resize_to_square()

    def _resize_to_square(self):
        """Auto-resize every saved image to 600×600 JPEG."""
        try:
            path = self.image.path
            with PILImage.open(path) as img:
                if img.size == (600, 600):
                    return
                img = img.convert('RGB')
                img = img.resize((600, 600), PILImage.LANCZOS)
                img.save(path, 'JPEG', quality=85, optimize=True)
        except Exception:
            pass


class ProductVariant(models.Model):
    product      = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='variants'
    )
    variant_name = models.CharField(max_length=100, blank=True)
    size         = models.CharField(max_length=50, blank=True)
    color        = models.CharField(max_length=100, blank=True)
    stock        = models.PositiveIntegerField(default=0)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['variant_name', 'size']

    def __str__(self):
        parts = [self.variant_name, self.size, self.color]
        return f"{self.product.name} — {' · '.join(p for p in parts if p)}"