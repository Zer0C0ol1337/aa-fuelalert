"""URL routes for aa-fuelalert. All routes require login and fuelalert.basic_access."""

from django.urls import path

from . import views

app_name = "fuelalert"

urlpatterns = [
    path("", views.index, name="index"),  # dashboard + own settings
    path("settings/save/", views.save_recipient, name="save_recipient"),  # POST
    path("settings/test/", views.send_test, name="send_test"),  # POST
    path("settings/delete/", views.delete_recipient, name="delete_recipient"),  # POST
]
