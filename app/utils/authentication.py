from rest_framework.authentication import TokenAuthentication as RestTokenAuthentication

from django.contrib.sessions.models import Session
from django.utils import timezone


class TokenAuthentication(RestTokenAuthentication):
    """Token auth using our custom Token model (supports multiple tokens per user)."""

    def authenticate_credentials(self, key):
        from app.core.users.authtoken.models import Token

        try:
            token = Token.objects.select_related("user").get(key=key)
        except Token.DoesNotExist as exc:
            from rest_framework.exceptions import AuthenticationFailed

            raise AuthenticationFailed("Invalid token.") from exc

        if not token.user.is_active:
            from rest_framework.exceptions import AuthenticationFailed

            raise AuthenticationFailed("User inactive or deleted.")

        token.last_used = timezone.now()
        token.save(update_fields=["last_used"])
        return (token.user, token)


def login_session(*, session: Session, user):
    """Login a user to a specific session (used for QR code login)"""

    session_data = session.get_decoded()
    session_data["_auth_user_id"] = str(user.pk)
    session_data["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    session_data["_auth_user_hash"] = user.get_session_auth_hash()
    session.session_data = Session.objects.encode(session_data)
    session.save()
