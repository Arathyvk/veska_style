import uuid
import base64


from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from cloudinary.models import CloudinaryField
from django.utils.timezone import now
from django.conf import settings


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    profile_pic = CloudinaryField("profile_pic", null=True, blank=True)    
    phone_number = models.CharField(max_length=15, null=True, blank=True)
    date_joined = models.DateTimeField(default=now)
    referred_by = models.ForeignKey('users.ReferralCode', null=True, blank=True, on_delete=models.SET_NULL,related_name='referred_users')
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_users',  
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_users_permissions', 
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self):
        return self.email
    

    def save_cropped_photo(self, base64_data):
        if not base64_data:
            return
        
        if ',' in base64_data:
            base64_data = base64_data.split(',')[1]
        import base64 as b64
        import cloudinary.uploader
        image_bytes = b64.b64decode(base64_data)
        result = cloudinary.uploader.upload(
            image_bytes,
            folder="profile_photos",
            public_id=f"profile_{self.pk}",
            overwrite=True,
            crop="fill",
            width=400,
            height=400,
        )
        self.profile_pic = result['public_id']


class ReferralCode(models.Model):
    
    user            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,related_name='referral_codes')
    code            = models.CharField(max_length=50, unique=True)
    total_referrals = models.PositiveIntegerField(default=0)
    total_earnings  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at      = models.DateTimeField(auto_now_add=True)
    is_active       = models.BooleanField(default=True)
    

    def __str__(self):
        return f"{self.user.email} - {self.code}"


class ReferralTransaction(models.Model):
    referrer              = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='referral_transactions')
    referred_user         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='referred_by_transactions')
    referral_code         = models.ForeignKey(ReferralCode, on_delete=models.CASCADE, null=True, blank=True)
    amount_earned         = models.DecimalField(max_digits=10, decimal_places=2, default=0)          # referrer's reward
    referred_user_bonus   = models.DecimalField(max_digits=10, decimal_places=2, default=0)          # NEW: referred user's welcome bonus
    order_amount          = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    created_at             = models.DateTimeField(auto_now_add=True)
    is_credited            = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.referrer.email} referred {self.referred_user.email}"