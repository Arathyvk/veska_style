from decimal import Decimal
from django import template
from product_admin.models import ProductReview

register = template.Library()
 
 
@register.filter
def get_item(dictionary, key):
    
    if isinstance(dictionary, dict):
        return dictionary.get(key, {})
    return {}
 
@register.filter
def add_decimals(value, arg):
    try:
        return Decimal(str(value)) + Decimal(str(arg))
    except:
        return value 
    

@register.filter
def can_review(product, order):
    if not product or not order:
        return False
    
    reviewable_statuses = ['delivered', 'confirmed', 'returned']
    if order.status not in reviewable_statuses:
        return False
    
    existing_review = ProductReview.objects.filter(
        user=order.user,
        product=product,
        order_item__order=order
    ).exists()
    
    return not existing_review