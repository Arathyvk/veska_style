import uuid
import base64


from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from cloudinary.models import CloudinaryField
from django.utils.timezone import now


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
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    profile_pic = CloudinaryField("profile_pic", null=True, blank=True)    
    phone_number = models.CharField(max_length=15, null=True, blank=True)
    date_joined = models.DateTimeField(default=now)
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