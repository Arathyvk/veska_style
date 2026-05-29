from django.urls import path
from . import views


urlpatterns = [

    path("success/<uuid:uuid>/", views.payment_success, name="payment_success"),
    path("failure/", views.payment_failure, name="payment_failure"),
            


]