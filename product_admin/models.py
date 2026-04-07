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
    ('sandal', 'sandal'),
]


class Product(models.Model):
    uuid        = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name        = models.CharField(max_length=255)
    slug        = models.SlugField(max_length=300, unique=True, blank=True)
    price       = models.DecimalField(max_digits=10, decimal_places=2)
    original_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Leave blank if no discount. Must be higher than price."
    )
    coupon_code = models.CharField(
        max_length=50, blank=True,
        help_text="e.g. VESKA10 — shown with a 'click to copy' box on the product page."
    )
    highlights  = models.TextField(
        blank=True,
        help_text="One highlight per line, e.g. 'Handcrafted leather upper'."
    )
    color       = models.CharField(max_length=100, blank=True)
    category    = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    stock       = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
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
        return self.images.order_by('order').first()

    @property
    def all_images(self):
        return self.images.order_by('order')

    @property
    def total_stock(self):
        variant_total = sum(v.stock for v in self.variants.all())
        return variant_total if variant_total > 0 else self.stock

    @property
    def discount_percent(self):
        if self.original_price and self.original_price > self.price:
            savings = self.original_price - self.price
            return round((savings / self.original_price) * 100)
        return 0

    @property
    def savings(self):
        if self.original_price and self.original_price > self.price:
            return self.original_price - self.price
        return 0

    @property
    def highlight_list(self):
        if not self.highlights:
            return []
        return [h.strip() for h in self.highlights.splitlines() if h.strip()]



def product_image_upload_path(instance, filename):
    ext  = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    name = f"{uuid.uuid4().hex[:10]}.{ext}"
    return os.path.join('products', str(instance.product.uuid), name)


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
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

    SIZE_CHOICES = [
        ('US 6',  'US 6'),
        ('US 7',  'US 7'),
        ('US 8',  'US 8'),
        ('US 9',  'US 9'),
        ('US 10', 'US 10'),
        ('US 11', 'US 11'),
    ]

    product      = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    variant_name = models.CharField(max_length=100, blank=True)
    size         = models.CharField(max_length=50, choices=SIZE_CHOICES, blank=True)
    color        = models.CharField(max_length=100, blank=True)
    stock        = models.PositiveIntegerField(default=0)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['variant_name', 'size']

    def __str__(self):
        parts = [self.variant_name, self.size, self.color]
        return f"{self.product.name} — {' · '.join(p for p in parts if p)}"



RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]   


class ProductReview(models.Model):
    product     = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    author_name = models.CharField(max_length=120, default='Anonymous')

    rating      = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    body        = models.TextField()
    is_approved = models.BooleanField(
        default=False,
        help_text="Only approved reviews are shown to customers."
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering    = ['-created_at']
        verbose_name        = 'Product Review'
        verbose_name_plural = 'Product Reviews'

    def __str__(self):
        return f"{self.author_name} — {self.product.name} ({self.rating}★)"