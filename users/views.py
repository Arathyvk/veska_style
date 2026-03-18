from django.shortcuts import render

from .models import User

def home_view(request):
    name = f"{request.user.first_name} {request.user.last_name}" if request.user.is_authenticated else ""
    context = {
        "name" : name,
    }    
    
    return render(request, "landing.html", context)
