from django.contrib.auth.models import AbstractUser
from django.contrib.sessions.models import Session
from django.db import transaction

from app import managers, models
from app.utils.authentication import login_session

from .managers import UserManager


class User(
    AbstractUser,
    models.AppModel,
):
    """
    Custom user model for the PERMYT MCP requester.

    Regular users are created via QR-code login.
    Account managers are created by superusers.
    """

    SYSTEM_ID = "00000000-0000-0000-0000-000000000000"

    email = models.EmailField(unique=True, null=True)
    permyt_user_id = models.UUIDField(unique=True, db_index=True, null=True)

    is_account_manager = models.BooleanField(default=False)

    objects = UserManager()

    REQUIRED_FIELDS = []
    USERNAME_FIELD = "email"
    DELETED_USERNAME = "deleted-user"

    def __str__(self):
        return self.email or str(self.pk)


class LoginToken(models.AppModel):
    """Short-lived token binding a QR-code connect flow to a Django session.

    Created when the login page renders. When the broker's ``user_connect``
    callback arrives, ``PermytClient.process_user_connect()`` looks up this
    token, links or creates the User, and calls ``login()`` to authenticate
    the session.
    """

    DELETE_AFTER = 5 * 60  # in minutes

    token = models.CharField(max_length=2048, unique=True)
    user = models.ForeignKey(User, null=True, on_delete=models.CASCADE, related_name="login_tokens")
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="login_tokens")
    logged_in = models.BooleanField(default=False)
    objects = managers.SuperuserManager(superuser_field="is_account_manager")

    def login(self, user: User):
        """Mark this token as used for login (after the user has scanned the QR code)."""
        with transaction.atomic():
            token = LoginToken.objects.select_for_update().get(pk=self.pk)
            if token.logged_in:
                raise ValueError("This token has already been used for login.")

            if token.user and token.user != user:
                raise ValueError("This token is associated with a different user.")

            login_session(session=self.session, user=user)
            token.user = user
            token.logged_in = True
            token.save()
            # Reflect saved state on self
            self.user = user
            self.logged_in = True

    def __str__(self):
        return f"LoginToken({self.token[:12]}... user={self.user})"
