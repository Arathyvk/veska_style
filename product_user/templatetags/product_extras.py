from django import template
from django.template.defaulttags import register


@register.filter
def group_by_color(variants):
    if not variants:
        return []
    
    color_groups = {}
    for variant in variants:
        color = variant.color or 'Default'
        if color not in color_groups:
            color_groups[color] = []
        color_groups[color].append(variant)
    
    return color_groups.items()


@register.filter
def get_color_hex(variant):
  
    if variant and hasattr(variant, 'color_hex') and variant.color_hex:
        return variant.color_hex
    return '#CCCCCC'


@register.simple_tag
def color_image(product, color):
    for v in product.variants.all():
        if v.color == color:
            img = v.images.first()
            if img:
                return img.image.url
    return ''


@register.simple_tag
def variant_image(product, color, size):
    for v in product.variants.all():
        if v.color == color and v.size == size:
            img = v.images.first()
            if img:
                return img.image.url
    for v in product.variants.all():
        if v.color == color:
            img = v.images.first()
            if img:
                return img.image.url
    return ''