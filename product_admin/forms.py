from django import forms
from .models import Product, ProductVariant


class ProductForm(forms.ModelForm):
    class Meta:
        model  = Product
        fields = ['name', 'price', 'color', 'category', 'stock', 'description']
        widgets = {
            'name':        forms.TextInput(attrs={
                               'class': 'form-control',
                               'placeholder': 'e.g. Leather Sandal'}),
            'price':       forms.NumberInput(attrs={
                               'class': 'form-control',
                               'placeholder': '0'}),
            'color':       forms.TextInput(attrs={
                               'class': 'form-control',
                               'placeholder': 'e.g. Brown, White'}),
            'category':    forms.Select(attrs={'class': 'form-control'}),
            'stock':       forms.NumberInput(attrs={
                               'class': 'form-control',
                               'placeholder': '0'}),
            'description': forms.Textarea(attrs={
                               'class': 'form-control',
                               'rows': 5,
                               'placeholder': 'Product description...'}),
        }


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model  = ProductVariant
        fields = ['variant_name', 'size', 'color', 'stock']
        widgets = {
            'variant_name': forms.TextInput(attrs={
                                'class': 'form-control',
                                'placeholder': 'e.g. Standard'}),
            'size':         forms.TextInput(attrs={
                                'class': 'form-control',
                                'placeholder': 'e.g. 38, 40, 42'}),
            'color':        forms.TextInput(attrs={
                                'class': 'form-control',
                                'placeholder': 'e.g. Black'}),
            'stock':        forms.NumberInput(attrs={
                                'class': 'form-control',
                                'placeholder': '0'}),
        }


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class ProductImageUploadForm(forms.Form):
    images = forms.ImageField(
        widget=MultiFileInput(attrs={'multiple': True}),  
        required=False
    )