from django.contrib import admin
from django.db import models
from product_admin.models import Product, ProductVariant, ProductImage
from django.forms import TextInput

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 3
    fields = ("image", "order")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = ("size", "color",'color_hex', "price", "stock")


    formfield_overrides = {
        models.CharField: {
            'widget': TextInput(attrs={'type': 'color'})
        }
    }

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "size",
        "color",
        "price",
        "stock",
    )

    list_filter = (
        "color",
        "size",
    )

    search_fields = (
        "product__name",
        "color",
    )

    list_editable = (
        "price",
        "stock",
    )

    inlines = [
        ProductImageInline,
    ]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    inlines = [
        ProductVariantInline
    ]

    list_display = (
        "name",
        "category",
        "brand",
        "display_colors",
        "display_price",
        "display_stock",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
        "category",
        "brand",
        "is_featured",
    )

    search_fields = (
        "name",
        "description",
        "brand",
    )

    list_editable = (
        "is_active",
    )

    inlines = [
        ProductVariantInline,
    ]

    @admin.display(description="Colors")
    def display_colors(self, obj):
        return ", ".join(obj.colors) if obj.colors else "-"

    @admin.display(description="Price")
    def display_price(self, obj):
        return obj.min_price if obj.min_price is not None else "-"

    @admin.display(description="Stock")
    def display_stock(self, obj):
        return obj.total_stock