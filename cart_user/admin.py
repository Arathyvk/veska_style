from django.contrib import admin
from django.utils.html import format_html
from cart_user.models import Cart, CartItem


class CartItemInline(admin.TabularInline):
    model         = CartItem
    extra         = 0
    readonly_fields = ('product', 'variant', 'quantity', 'unit_price_display',
                       'line_total_display', 'stock_display')
    can_delete    = True

    def unit_price_display(self, obj):
        return f'₹{obj.unit_price:.2f}'
    unit_price_display.short_description = 'Unit price'

    def line_total_display(self, obj):
        return f'₹{obj.line_total:.2f}'
    line_total_display.short_description = 'Line total'

    def stock_display(self, obj):
        s = obj.available_stock
        if s == 0:
            return format_html('<span style="color:#b53333;font-weight:600">Out of stock</span>')
        return s
    stock_display.short_description = 'Stock'


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display  = ('user', 'total_items_display', 'subtotal_display', 'updated_at')
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('created_at', 'updated_at')
    inlines       = [CartItemInline]

    def total_items_display(self, obj):
        return obj.total_items
    total_items_display.short_description = 'Items'

    def subtotal_display(self, obj):
        return f'₹{obj.subtotal:.2f}'
    subtotal_display.short_description = 'Subtotal'