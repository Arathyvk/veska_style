from django.contrib import admin
from django.utils.html import format_html
from order_user.models import Order, OrderItem, Coupon


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):

    list_display = (
        'code', 'discount_type', 'display_value',
        'min_order_value', 'times_used', 'usage_limit',
        'valid_from', 'valid_until', 'status_badge'
    )

    list_filter = ('discount_type', 'is_active')
    search_fields = ('code',)
    ordering = ('-valid_from',)

    readonly_fields = ('times_used',)

    fieldsets = (
        ('Coupon Code', {
            'fields': ('code', 'is_active')
        }),
        ('Discount', {
            'fields': ('discount_type', 'value', 'min_order_value', 'max_discount')
        }),
        ('Validity', {
            'fields': ('valid_from', 'valid_until')
        }),
        ('Usage', {
            'fields': ('usage_limit', 'times_used')
        }),
    )

    def display_value(self, obj):
        if obj.discount_type == 'flat':
            return f'₹{obj.value:.0f} off'
        text = f'{obj.value:.0f}% off'
        if obj.max_discount:
            text += f' (max ₹{obj.max_discount:.0f})'
        return text
    display_value.short_description = 'Discount'

    def status_badge(self, obj):
        valid, reason = obj.is_valid()

        if valid:
            return format_html(
                '<span style="background:#eaf4ee;color:#3a7d5a;padding:2px 10px;'
                'border-radius:12px;font-size:11px;font-weight:600">✓ Active</span>'
            )

        return format_html(
            '<span style="background:#fdf0f0;color:#b53333;padding:2px 10px;'
            'border-radius:12px;font-size:11px;font-weight:600" title="{}">✗ Inactive</span>',
            reason,
        )

    status_badge.short_description = 'Status'



class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False

    readonly_fields = (
        'product', 'product_name', 'size',
        'unit_price', 'quantity',
        'line_total_display',
        'item_status_badge',
        'cancel_reason',
    )

    fields = (
        'product_name', 'size', 'unit_price', 'quantity',
        'line_total_display', 'item_status_badge', 'cancel_reason',
    )

    def line_total_display(self, obj):
        return f'₹{obj.line_total:.2f}'
    line_total_display.short_description = 'Total'

    def item_status_badge(self, obj):
        if obj.status == 'cancelled':
            return format_html(
                '<span style="background:#fdf0f0;color:#b53333;padding:2px 8px;'
                'border-radius:10px;font-size:11px;font-weight:600">Cancelled</span>'
            )
        return format_html(
            '<span style="background:#eaf4ee;color:#3a7d5a;padding:2px 8px;'
            'border-radius:10px;font-size:11px;font-weight:600">Active</span>'
        )
    item_status_badge.short_description = 'Item Status'



STATUS_COLORS = {
    'pending':          ('#fef8ec', '#c47f17'),
    'confirmed':        ('#e6f1fb', '#185fa5'),
    'processing':       ('#e6f1fb', '#185fa5'),
    'shipped':          ('#f2ede6', '#8f4f31'),
    'delivered':        ('#eaf4ee', '#3a7d5a'),
    'cancelled':        ('#fdf0f0', '#b53333'),
    'return_requested': ('#fef8ec', '#c47f17'),
    'returned':         ('#f1efe8', '#5f5e5a'),
}


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):


    list_display = (
        'uuid', 'user_display', 'full_name',
        'phone', 'city', 'total_display',
        'discount_display', 'status_badge',
        'payment_method', 'created_at',
    )

    list_filter = ('status', 'payment_method', 'created_at', 'country')
    search_fields = (
        'uuid', 'full_name', 'phone',
        'user__email', 'user__username',
        'city', 'coupon_code',
        'items__product_name',
    )

    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    list_per_page = 25

    inlines = [OrderItemInline]

    actions = [
        'mark_confirmed', 'mark_processing',
        'mark_shipped', 'mark_delivered',
    ]
    readonly_fields = (
        'uuid', 'user', 'created_at', 'updated_at',
        'subtotal', 'discount_amount', 'shipping_charge',
        'wallet_amount_used', 'total', 'coupon_code',
    )

   
    fieldsets = (
        ('Order Info', {
            'fields': (
                'uuid', 'user', 'status',
                'payment_method', 'notes',
                'created_at', 'updated_at',
            ),
        }),
        ('Delivery Address', {
            'fields': (
                'full_name', 'phone',
                'address_line1', 'address_line2',
                'city', 'state', 'pincode', 'country',
            ),
        }),
        ('Pricing', {
            'fields': (
                'subtotal', 'coupon_code',
                'discount_amount',
                'shipping_charge', 'total',
            ),
        }),
    
    )

  
    def order_number_link(self, obj):
        return format_html(
            '<a href="/admin/checkout_page/order/{}/change/" '
            'style="font-family:monospace;font-weight:600;color:#b56744">{}</a>',
            obj.pk, obj.uuid
        )
    order_number_link.short_description = 'Order #'

    def user_display(self, obj):
        if obj.user:
            return format_html(
                '{}<br/><span style="color:#7a6f66;font-size:11px">{}</span>',
                obj.user.get_full_name() or obj.user.username,
                obj.user.email,
            )
        return '—'
    user_display.short_description = 'User'

    def total_display(self, obj):
        return format_html('<strong>₹{}</strong>', f'{obj.total:.2f}')
    total_display.short_description = 'Total'

    def discount_display(self, obj):
        if obj.discount_amount:
            return format_html(
                '<span style="color:#3a7d5a;font-weight:600">−₹{}</span>',
                f'{obj.discount_amount:.2f}',
            )
        return '—'
    discount_display.short_description = 'Discount'

    def status_badge(self, obj):
        bg, fg = STATUS_COLORS.get(obj.status, ('#f1efe8', '#5f5e5a'))
        return format_html(
            '<span style="background:{};color:{};padding:3px 10px;'
            'border-radius:12px;font-size:11px;font-weight:600">{}</span>',
            bg, fg, obj.get_status_display(),
        )
    status_badge.short_description = 'Status'

    def _bulk_status(self, request, queryset, status, label):
        count = queryset.update(status=status)
        self.message_user(request, f'{count} order(s) marked as {label}.')

    def mark_confirmed(self, request, queryset):
        self._bulk_status(request, queryset, 'confirmed', 'Confirmed')

    def mark_processing(self, request, queryset):
        self._bulk_status(request, queryset, 'processing', 'Processing')

    def mark_shipped(self, request, queryset):
        self._bulk_status(request, queryset, 'shipped', 'Shipped')

    def mark_delivered(self, request, queryset):
        self._bulk_status(request, queryset, 'delivered', 'Delivered')