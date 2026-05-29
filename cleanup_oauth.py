#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'veska_fashion.settings')
django.setup()

from allauth.socialaccount.models import SocialApp

# Find all Google OAuth apps
google_apps = SocialApp.objects.filter(provider='google')
print(f"Found {google_apps.count()} Google OAuth apps")

if google_apps.count() > 1:
    print("\nApps found:")
    for app in google_apps:
        print(f"  ID: {app.id}, Name: {app.name}, Client ID: {app.client_id}")
    
    # Keep the first one, delete the rest
    first_app = google_apps.first()
    print(f"\nKeeping app ID {first_app.id}")
    
    deleted_count, _ = google_apps.exclude(id=first_app.id).delete()
    print(f"Deleted {deleted_count} duplicate apps")
    print("\n✓ OAuth cleanup complete!")
else:
    print("Only 1 Google OAuth app found - no cleanup needed ✓")
