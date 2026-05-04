from django.db import models
import uuid
import os
from django.utils.text import slugify
from PIL import Image as PILImage
from category_admin.models import Category


CATEGORY_CHOICES = [
    ('Formal', 'Formal'),
    ('Casual', 'Casual'),
    ('Party',  'Party'),
    ('Sports', 'Sports'),
    ('Ethnic', 'Ethnic'),
    ('Sandal', 'Sandal'),
]


class Product(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=300, unique=True, blank=True)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)    
    color = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    is_listed = models.BooleanField(default=True)
    is_blocked = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_featured = models.BooleanField(default=False)
    is_shop_active = models.BooleanField(default=True)  


    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug = base
            n = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

  
    @property
    def primary_image(self):
        return self.images.first()

    @property
    def total_stock(self):
        variant_total = sum(v.stock for v in self.variants.all())
        return variant_total if variant_total > 0 else self.stock

    @property
    def discount_percent(self):
        if self.original_price and self.original_price > self.price:
            return round(((self.original_price - self.price) / self.original_price) * 100)
        return 0
    


def product_image_upload_path(instance, filename):
    ext = filename.rsplit('.', 1)[-1].lower()
    name = f"{uuid.uuid4().hex[:10]}.{ext}"
    return os.path.join('products', str(instance.product.uuid), name)


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=product_image_upload_path)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.resize_image()

    def resize_image(self):
        try:
            path = self.image.path
            with PILImage.open(path) as img:
                img = img.convert('RGB')
                img = img.resize((600, 600), PILImage.LANCZOS)
                img.save(path, 'JPEG', quality=85)
        except Exception:
            pass

    def __str__(self):
        return f"{self.product.name} Image"
    

class ProductVariant(models.Model):

    SIZE_CHOICES = [
        ('US 6', 'US 6'),
        ('US 7', 'US 7'),
        ('US 8', 'US 8'),
        ('US 9', 'US 9'),
        ('US 10', 'US 10'),
        ('US 11', 'US 11'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')

    size = models.CharField(max_length=50, choices=SIZE_CHOICES)
    color = models.CharField(max_length=100, blank=True)

    stock = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)



    def __str__(self):
        return f"{self.product.name} - {self.size}"    
    


class ProductReview(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')

    author_name = models.CharField(max_length=120, default='Anonymous')
    rating = models.PositiveSmallIntegerField()
    body = models.TextField()

    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.author_name} - {self.product.name}"    