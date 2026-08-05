from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()

class EmailBackend(ModelBackend):
    """
    Custom authentication backend that authenticates using email.
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate a user by email and password.
        
        Args:
            request: The HTTP request
            username: The email address (Django passes it as 'username')
            password: The user's password
            **kwargs: Additional arguments (may include 'email')
        """
        # Check if email is provided in kwargs or as username
        email = kwargs.get('email') or username
        
        if email is None or password is None:
            return None
        
        # Try to find the user with case-insensitive email
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Still run password hashing to prevent timing attacks
            User().set_password(password)
            return None
        
        # Check password and if user can authenticate
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        
        return None
    
    def get_user(self, user_id):
        """
        Retrieve a user by their UUID primary key.
        """
        try:
            # user_id should be a UUID object or string
            return User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError):
            return None