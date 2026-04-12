from django import forms
from product_admin.models import Product, ProductVariant


class ProductForm(forms.ModelForm):

    class Meta:
        model  = Product
        fields = ['name', 'price', 'color', 'category', 'stock', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class'      : 'finput',
                'placeholder': 'e.g. Womens Vintage Flock Loafers',
            }),
            'price': forms.NumberInput(attrs={
                'class'      : 'finput',
                'placeholder': '0.00',
                'step'       : '0.01',
                'min'        : '0',
            }),
            'color': forms.TextInput(attrs={
                'class'      : 'finput',
                'placeholder': 'e.g. Brown, White',
            }),
            'category': forms.Select(attrs={
                'class': 'fselect',
            }),
            'stock': forms.NumberInput(attrs={
                'class'      : 'finput',
                'placeholder': '0',
                'min'        : '0',
            }),
            'description': forms.Textarea(attrs={
                'class'      : 'ftextarea',
                'placeholder': 'Describe the product — material, use, style…',
                'rows'       : '4',
            }),
            'is_active': forms.CheckboxInput(),
        }

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None and price < 0:
            raise forms.ValidationError('Price cannot be negative.')
        return price

    def clean_stock(self):
        stock = self.cleaned_data.get('stock')
        if stock is not None and stock < 0:
            raise forms.ValidationError('Stock cannot be negative.')
        return stock


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ['size', 'color', 'stock', 'price']  

        widgets = {
            'size': forms.Select(attrs={
                'class': 'finput',
            }),
            'color': forms.TextInput(attrs={
                'class': 'finput',
                'placeholder': 'Color',
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'finput',
                'placeholder': '0',
                'min': '0',
            }),
            'price': forms.NumberInput(attrs={
                'class': 'finput',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0',
            }),
        }