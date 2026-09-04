from django.db import models
import uuid
import os
import logging
from django.db.models import Sum, Min
from django.utils.text import slugify
from PIL import Image as PILImage
from category_admin.models import Category
from django.conf import settings

CATEGORY_CHOICES = [
    ('Sneakers', 'Sneakers'),
    ('Heels', 'Heels'),
    ('Flats', 'Flats'),
    ('Boots', 'Boots'),
    ('Sandals', 'Sandals'),
    ('Loafers', 'Loafers'),
    ('Sports Shoes', 'Sports Shoes'),
    ('Casual', 'Casual'),
]

logger = logging.getLogger(__name__)

class Product(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=300, unique=True, blank=True)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    brand = models.CharField(max_length=100, blank=True)
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
    def all_images(self):
        return ProductImage.objects.filter(variant__product=self).order_by("order", "id")
    
    @property
    def primary_image(self):
        return (
            ProductImage.objects
            .filter(variant__product=self)
            .order_by("order", "id")
            .first()
        )

    @property
    def total_stock(self):
        return self.variants.aggregate(
            total=Sum("stock")
        )["total"] or 0

    @property
    def min_price(self):
        return self.variants.aggregate(
            Min("price")
        )["price__min"]

    @property
    def price(self):
        return self.min_price or 0

    @property
    def colors(self):
        return sorted(set(v.color for v in self.variants.all() if v.color))


    def get_best_offer(self, amount=None):
        from offer_admin.models import BaseOffer  
        from django.db.models import Q
        from django.utils import timezone

        amount = self.price if amount is None else amount
        now = timezone.now()
        offers = BaseOffer.objects.filter(
            is_active=True, start_date__lte=now, end_date__gte=now,
        ).filter(
            Q(offer_type='PRODUCT', products=self) | Q(offer_type='CATEGORY', categories=self.category)
        )
        best_offer, best_disc = None, 0
        for o in offers:
            if o.is_valid:
                disc = o.calculate_discount(amount)
                if disc > best_disc:
                    best_offer, best_disc = o, disc
        return best_offer


    @property
    def discounted_price(self):
        offer = self.get_best_offer(self.price)
        if offer:
            return self.price - offer.calculate_discount(self.price)
        return self.price


def product_image_upload_path(instance, filename):
    ext = filename.rsplit('.', 1)[-1].lower()
    name = f"{uuid.uuid4().hex[:10]}.{ext}"
    return os.path.join(
        "products",
        str(instance.variant.product.uuid),
        str(instance.variant.id),
        name,
    )


class ProductImage(models.Model):
    variant = models.ForeignKey("ProductVariant",on_delete=models.CASCADE,related_name="images")
    image   = models.ImageField(upload_to=product_image_upload_path)
    order   = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.resize_image()

    def resize_image(self):
        try:
            path = self.image.path
            with PILImage.open(path) as img:
                img = img.convert("RGB")
                img = img.resize((600, 600), PILImage.LANCZOS)
                img.save(path, "JPEG", quality=85)
        except Exception as e:
            logger.error(f"Failed to resize ProductImage id={self.pk} (path={self.image.name}): {e}")


    def __str__(self):
        if self.variant:
            return f"{self.variant.product.name} - {self.variant.size}"
        return "Unassigned Image"


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
    size    = models.CharField(max_length=50, choices=SIZE_CHOICES)
    color   = models.CharField(max_length=100, blank=True, null=True)
    stock   = models.PositiveIntegerField(default=0)
    price   = models.DecimalField(max_digits=10, decimal_places=2)  

    def __str__(self):
        return f"{self.product.name} - {self.size}"


class ProductReview(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews', null=True, blank=True)
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='reviews')
    author_name = models.CharField(max_length=120, default='Anonymous')
    rating = models.PositiveSmallIntegerField()
    body = models.TextField()
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "product"],
                name="unique_user_product_review",
            )
        ]

    def __str__(self):
        return f"{self.author_name} - {self.product.name}"

    def save(self, *args, **kwargs):
        if not self.author_name or self.author_name == 'Anonymous':
            if self.user:
                self.author_name = (
                    f"{self.user.first_name} {self.user.last_name or ''}"
                ).strip()
                if not self.author_name:
                    self.author_name = self.user.email
        super().save(*args, **kwargs)