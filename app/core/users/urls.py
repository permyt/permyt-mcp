from django.urls import path

from rest_framework import routers

from .authtoken.views import LoginView, LogoutView, TokenViewSet
from . import views

router = routers.SimpleRouter()
router.register("auth/token", TokenViewSet, "auth-token")

urlpatterns = [
    path("auth/token/login/", LoginView.as_view(), name="auth-login"),
    path("auth/token/logout/", LogoutView.as_view(), name="auth-logout"),
    path("login/status/", views.LoginStatusView.as_view(), name="login-status"),
] + router.urls
