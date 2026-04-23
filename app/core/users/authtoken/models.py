from django.conf import settings
from django.db import IntegrityError, models

from app.managers import OwnerManager
from app.utils.crypto import generate_token, hide_token


class Token(models.Model):
    """
    Token for API authentication. Supports multiple named tokens per user.

    system=True tokens are created on QR login (one per user).
    system=False tokens are created by users for API/MCP use.
    """

    key = models.CharField(max_length=256, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="auth_tokens",
        on_delete=models.CASCADE,
    )

    name = models.CharField(max_length=64, null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    system = models.BooleanField(default=False)

    objects = OwnerManager(field="user")

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = generate_token(128)
        try:
            return super().save(*args, **kwargs)
        except IntegrityError:
            # Extremely unlikely collision on 128-byte urlsafe token; retry once
            self.key = generate_token(128)
            return super().save(*args, **kwargs)

    @property
    def hidden_key(self):
        return hide_token(self.key, chars=4)

    def __str__(self):
        return f"{self.name or 'Unnamed'} ({self.user})"
