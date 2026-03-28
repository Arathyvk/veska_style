from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model

User = get_user_model()


class AccountAdapter(DefaultAccountAdapter):
    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        data = form.cleaned_data
        user.first_name = data.get('first_name', '')
        user.last_name  = data.get('last_name', '')
        if commit:
            user.save()
        return user

    def populate_username(self, request, user):
        pass


class SocialAccountAdapter(DefaultSocialAccountAdapter):

    def pre_social_login(self, request, sociallogin):
        
        email = sociallogin.account.extra_data.get('email', '').strip().lower()
        if not email:
            return
        try:
            existing_user = User.objects.get(email=email)
            sociallogin.connect(request, existing_user)
        except User.DoesNotExist:
            pass

    def populate_user(self, request, sociallogin, data):
       
        user = super().populate_user(request, sociallogin, data)
        extra = sociallogin.account.extra_data

        user.first_name = extra.get('given_name') or data.get('first_name', 'Google')
        user.last_name  = extra.get('family_name') or data.get('last_name', '')

        picture = extra.get('picture', '')
        if picture:
            user.profile_pic = picture

        return user

    def save_user(self, request, sociallogin, form=None):
        
        user = super().save_user(request, sociallogin, form)
        extra = sociallogin.account.extra_data

        if not user.first_name:
            user.first_name = extra.get('given_name', 'Google User')
        if not user.last_name:
            user.last_name = extra.get('family_name', '')

        user.save()
        return user