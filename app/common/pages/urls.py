from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import IndexView

urlpatterns = [
    path("", IndexView.as_view(), name="index"),
    path("logout/", LogoutView.as_view(next_page="/"), name="logout"),
]
