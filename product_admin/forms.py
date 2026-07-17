from django import forms
from product_admin.models import Product, ProductVariant
from category_admin.models import Category  


class ProductForm(forms.ModelForm):

    class Meta:
        model  = Product
        fields = ['name', 'price', 'brand', 'color', 'category', 'stock', 'description', 'is_active', 'is_featured', 'is_shop_active']  # Added is_shop_active
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
            'brand' : forms.TextInput(attrs={
                'class'      : 'finput',
                'placeholder': 'e.g. Adidas, Nike',
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
            'is_active': forms.CheckboxInput(attrs={
                'class': 'toggle-input',
            }),
            'is_featured': forms.CheckboxInput(attrs={
                'class': 'toggle-input',
            }),
            'is_shop_active': forms.CheckboxInput(attrs={
                'class': 'toggle-input',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.all()
        self.fields['category'].empty_label = "— Select —"
        self.fields['category'].label_from_instance = lambda obj: obj.name
        
        self.fields['is_active'].required = False
        self.fields['is_featured'].required = False
        self.fields['is_shop_active'].required = False

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