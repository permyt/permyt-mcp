from datetime import datetime

from django.conf import settings

from app import models


class Nonce(models.AppModel):
    """Nonce model for replay attack prevention."""

    DELETE_AFTER = 5  # in minutes

    value = models.CharField(max_length=128, unique=True)
    objects = models.Manager()

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Nonce({self.value[:8]}...)"


class PendingServiceCall(models.AppModel):
    """Bridges ``permyt_check_access(completed)`` and ``permyt_call_service``.

    Stored when polling first sees ``status="completed"`` so the encrypted
    ``ServiceCredential`` list (single-use provider tokens + endpoints +
    provider public keys) does not have to round-trip through the calling AI.
    The AI then invokes ``permyt_call_service(request_id, inputs)`` to execute
    the call with dynamic inputs; this row is consumed at that point.

    ``expires_at`` mirrors the earliest token expiry across ``services``;
    expired or already-consumed rows are rejected.
    """

    request_id = models.CharField(max_length=128, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    services = models.EncryptedJSONField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    objects = models.Manager()

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"PendingServiceCall({self.request_id})"

    @staticmethod
    def expires_at_from_services(services: list[dict]) -> datetime:
        """Earliest ``ServiceCredential.expires_at`` — we cannot outlive any token."""
        return min(datetime.fromisoformat(s["expires_at"]) for s in services)
