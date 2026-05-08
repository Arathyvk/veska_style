from django import template
 
register = template.Library()
 
 
@register.filter
def get_item(dictionary, key):
    """
    Retrieve a value from a dict by key in Django templates.
    Usage:  {{ my_dict|get_item:my_key }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key, {})
    return {}
 