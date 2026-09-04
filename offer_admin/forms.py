from django import forms
from django.utils import timezone
from .models import BaseOffer

class BaseOfferForm(forms.ModelForm):
    class Meta:
        model = BaseOffer
        fields = [
            'name', 'offer_type', 'discount_type', 'discount_value',
            'products', 'categories', 'start_date', 'end_date',
            'min_purchase_amount', 'max_discount_amount',
            'usage_limit', 'per_user_limit', 'is_active'
        ]

        widgets = {
            'start_date': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={
                    'type': 'datetime-local'
                }
            ),

            'end_date': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={
                    'type': 'datetime-local'
                }
            ),

            'products': forms.SelectMultiple(attrs={'size': 8}),
            'categories': forms.SelectMultiple(attrs={'size': 5}),
            'discount_value': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'min_purchase_amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'max_discount_amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['start_date'].input_formats = ['%Y-%m-%dT%H:%M']
        self.fields['end_date'].input_formats = ['%Y-%m-%dT%H:%M']

    def clean(self):
        cleaned_data = super().clean()

        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        offer_type = cleaned_data.get('offer_type')
        products = cleaned_data.get('products')
        categories = cleaned_data.get('categories')
        discount_type = cleaned_data.get('discount_type')
        discount_value = cleaned_data.get('discount_value')
        min_purchase_amount = cleaned_data.get('min_purchase_amount')
        max_discount_amount = cleaned_data.get('max_discount_amount')

        if start_date and end_date and start_date >= end_date:
            raise forms.ValidationError('End date must be after start date')

        if offer_type == 'PRODUCT' and not products:
            raise forms.ValidationError(
                'Please select at least one product for Product Offer'
            )

        if offer_type == 'CATEGORY' and not categories:
            raise forms.ValidationError(
                'Please select at least one category for Category Offer'
            )

        if discount_value is not None and discount_value <= 0:
            self.add_error('discount_value', 'Discount value must be greater than zero.')
        if discount_type == 'PERCENTAGE' and discount_value is not None and discount_value > 100:
            self.add_error('discount_value', 'Percentage discount cannot exceed 100%.')
        if min_purchase_amount is not None and min_purchase_amount < 0:
            self.add_error('min_purchase_amount', 'Minimum purchase amount cannot be negative.')
        if max_discount_amount is not None and max_discount_amount <= 0:
            self.add_error('max_discount_amount', 'Maximum discount must be greater than zero.')
        if (max_discount_amount is not None and discount_type == 'FIXED'
                and discount_value is not None and max_discount_amount > discount_value):
            self.add_error('max_discount_amount', 'A fixed discount cap cannot exceed the discount value.')

        return cleaned_data


class ReferralOfferForm(forms.ModelForm):
    class Meta:
        model = BaseOffer
        fields = [
            'name', 'discount_type', 'discount_value',
            'referral_code', 'referral_reward_amount', 'referred_user_reward',
            'start_date', 'end_date', 'min_purchase_amount',
            'max_discount_amount', 'usage_limit', 'per_user_limit', 'is_active'
        ]
        widgets = {
            'start_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'end_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'discount_value': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'referral_reward_amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'referred_user_reward': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.offer_type = 'REFERRAL'

    def clean(self):
        cleaned_data = super().clean()
        discount_type = cleaned_data.get('discount_type')
        discount_value = cleaned_data.get('discount_value')
        min_purchase_amount = cleaned_data.get('min_purchase_amount')
        max_discount_amount = cleaned_data.get('max_discount_amount')

        if discount_value is not None and discount_value <= 0:
            self.add_error('discount_value', 'Discount value must be greater than zero.')
        if discount_type == 'PERCENTAGE' and discount_value is not None and discount_value > 100:
            self.add_error('discount_value', 'Percentage discount cannot exceed 100%.')
        if min_purchase_amount is not None and min_purchase_amount < 0:
            self.add_error('min_purchase_amount', 'Minimum purchase amount cannot be negative.')
        if max_discount_amount is not None and max_discount_amount <= 0:
            self.add_error('max_discount_amount', 'Maximum discount must be greater than zero.')
        if (max_discount_amount is not None and discount_type == 'FIXED'
                and discount_value is not None and max_discount_amount > discount_value):
            self.add_error('max_discount_amount', 'A fixed discount cap cannot exceed the discount value.')

        return cleaned_data