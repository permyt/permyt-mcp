from django.apps import AppConfig


class AuthTokenConfig(AppConfig):
    name = "app.core.users.authtoken"
    label = "user_tokens"
    verbose_name = "User Auth Tokens"
