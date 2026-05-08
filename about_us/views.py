from django.shortcuts import render,redirect
from django.contrib import messages
from .models import ContactMessage

def contact_us(request):
    if request.method == "POST":

        name    = request.POST.get('name', '').strip()
        email   = request.POST.get('email', '').strip()
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip() 


        error ={}
        if not name:
           error['name'] = "Name is required"    

        if not email:
            error['email'] = "Email is required"

        if not message:
            error['message'] =  "Message is required"

        if not error:
            ContactMessage.objects.create(
                name    = name, 
                email   = email,
                subject = subject,
                messages = messages

            ) 
            messages.success(request, "Thank you! Your message has been sent. We'll get back to you soon.")

            return redirect('contact_us')      
        return render(request, 'contact_us.html',{
            'error'     : error,
            'form_data' : request.POST
        })           

    return render(request, 'contact_us.html')



def about_us(request):
    return render(request, 'about_us.html')