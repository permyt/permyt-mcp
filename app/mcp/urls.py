from django.urls import path

from .views import OAuthAuthorizeView, OAuthCallbackView

urlpatterns = [
    path("authorize/", OAuthAuthorizeView.as_view(), name="oauth-authorize"),
    path("callback/", OAuthCallbackView.as_view(), name="oauth-callback"),
]
