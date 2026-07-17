from django.contrib import admin
from product_admin.models import Product, ProductImage, ProductVariant


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 3
    fields = ('image', 'order')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'brand', 'color', 'price', 'stock', 'is_active', 'created_at')
    list_filter = ('is_active', 'category', 'brand')
    search_fields = ('name', 'description', 'brand')
    inlines = [ProductImageInline]
    list_editable = ('is_active', 'stock', 'brand')


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('product', 'size', 'color', 'stock', 'price')
    search_fields = ('product__name',)