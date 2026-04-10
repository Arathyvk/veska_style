from django.http import HttpResponse


def order_view(request):
    return HttpResponse("this is order page")
