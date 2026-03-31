from django.db import models
import uuid


CATEGORY_CHOICES = [
    ('Formal',  'Formal'),
    ('Casual',  'Casual'),
    ('Party',   'Party'),
    ('Sports',  'Sports'),
    ('Ethnic',  'Ethnic'),
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
        img = self.images.first()
        return img.image.url if img else None

    @property
    def all_images(self):
        return self.images.all()


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image   = models.ImageField(upload_to='products/')
    order   = models.PositiveIntegerField(default=0)   

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.product.name} — image {self.order}"


class ProductVariant(models.Model):
    product      = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    variant_name = models.CharField(max_length=100, blank=True)
    size         = models.CharField(max_length=50, blank=True)
    color        = models.CharField(max_length=100, blank=True)
    stock        = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.product.name} — {self.size} {self.color}"