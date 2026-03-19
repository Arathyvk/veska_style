import re
from django.core.exceptions import ValidationError

class StrongPasswordValidator:
    def validate(self, password, user=None):
        errors = []
        if len(password) < 8:
            errors.append("at least 8 characters")
        if not re.search(r'[A-Z]', password):
            errors.append("one uppercase letter (A–Z)")
        if not re.search(r'[a-z]', password):
            errors.append("one lowercase letter (a–z)")
        if not re.search(r'\d', password):
            errors.append("one digit (0–9)")
        if not re.search(r'[!@#$%^&*(),.?\":{}|<>_\-]', password):
            errors.append("one special character (!@#$%^&* etc.)")
        if errors:
            raise ValidationError(f"Password must contain: {', '.join(errors)}.")

    def get_help_text(self):
        return (
            "At least 8 characters with one uppercase, "
            "one lowercase, one digit, and one special character."
        )