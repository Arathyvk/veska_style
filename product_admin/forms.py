from django import forms
from django.forms import inlineformset_factory
from product_admin.models import Product, ProductVariant
from category_admin.models import Category


from django import forms
from django.core.exceptions import ValidationError
from .models import Product
import re


class ProductForm(forms.ModelForm):

    class Meta:
        model = Product
        fields = [
            'name',
            'brand',
            'category',
            'description',
            'is_active',
            'is_featured',
            'is_shop_active'
        ]

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'finput',
                'placeholder': 'e.g. Womens Vintage Flock Loafers',
            }),
            'brand': forms.TextInput(attrs={
                'class': 'finput',
                'placeholder': 'e.g. Adidas',
            }),
            'category': forms.Select(attrs={
                'class': 'fselect',
            }),
            'description': forms.Textarea(attrs={
                'class': 'ftextarea',
                'placeholder': 'Describe the product...',
                'rows': '4',
            }),

            
            'is_active': forms.CheckboxInput(attrs={'class': 'toggle-input'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'toggle-input'}),
            'is_shop_active': forms.CheckboxInput(attrs={'class': 'toggle-input'}),
        }

    def clean_name(self):
        print("clean_name called")
        name = self.cleaned_data.get("name", "").strip()

        if not re.fullmatch(r"[A-Za-z0-9\s.,()\-\/&%!?;:'\"]+", name):
            raise forms.ValidationError(
                "Product name can contain only letters and spaces."
            )

        return name

    def clean_brand(self):
        brand = self.cleaned_data.get('brand', '').strip()

        if brand and not re.fullmatch(r"[A-Za-z0-9\s.,()\-\/&%!?;:'\"]+", brand):
            raise ValidationError(
                "Brand can contain only letters and spaces."
            )

        return brand


    def clean_description(self):
        description = self.cleaned_data.get("description", "").strip()

        if description and not re.fullmatch(
            r"[A-Za-z0-9\s.,()\-\/&%!?;:'\"]+",
            description
        ):
            raise ValidationError(
                "Description contains invalid characters."
            )

        return description

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.all()
        self.fields['category'].empty_label = "— Select —"
        self.fields['category'].label_from_instance = lambda obj: obj.name

        self.fields['is_active'].required = False
        self.fields['is_featured'].required = False
        self.fields['is_shop_active'].required = False


import re
from django.core.exceptions import ValidationError

class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ['size', 'color', 'stock', 'price']
        widgets = {
            'size': forms.Select(attrs={'class': 'finput'}),
            'color': forms.TextInput(attrs={
                'class': 'finput',
                'placeholder': 'Color',
                'oninput': "this.value=this.value.replace(/[^A-Za-z ]/g,'')"
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'finput',
                'placeholder': '0',
                'min': '0'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'finput',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['size'].choices = [('', '— Size —')] + list(ProductVariant.SIZE_CHOICES)

    def clean_color(self):
        color = self.cleaned_data.get('color', '').strip()

        if not re.fullmatch(r'[A-Za-z ]+', color):
            raise ValidationError(
                "Color can contain only letters and spaces."
            )

        return color.title()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['size'].choices = [('', '— Size —')] + list(ProductVariant.SIZE_CHOICES)
        self.fields['color'].required = False   


ProductVariantFormSet = inlineformset_factory(
    Product, ProductVariant,
    form=ProductVariantForm,
    fields=['size', 'color', 'stock', 'price'],
    extra=1,
    can_delete=True,
    min_num=1,         
    validate_min=True,  
)