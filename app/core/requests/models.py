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
