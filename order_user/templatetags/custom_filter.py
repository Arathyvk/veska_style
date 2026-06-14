from decimal import Decimal
from django import template
 
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