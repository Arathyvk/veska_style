from django import forms
from .models import Category


class CategoryForm(forms.ModelForm):
    class Meta:
        model  = Category
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class':       'form-control',
                'placeholder': 'e.g. Formal',
                'autofocus':   True,
            }),
            'description': forms.Textarea(attrs={
                'class':       'form-control',
                'rows':        3,
                'placeholder': 'Optional description…',
            }),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        qs   = Category.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('A category with this name already exists.')
        return name