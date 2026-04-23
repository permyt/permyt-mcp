"""
Simplified AppModel for permyt-mcp.

Stripped of Celery background tasks and WebSocket notifications.
Keeps: UUID pk, timestamps, user tracking, permissions.
"""

from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from app.core.users.utils import set_delete_user
from app.managers import SuperuserManager
from app.permissions import PERMISSIONS
from app.utils.middleware import get_current_user


class PermissionsMixin:
    """Common permission checks delegated to the manager."""

    def _check_permissions(self, user, permission) -> bool:
        return self.__class__.objects.check_object_permission(self, user, permission)

    def can_read(self, user) -> bool:
        return self._check_permissions(user, PERMISSIONS.READ)

    def can_write(self, user) -> bool:
        return self._check_permissions(user, PERMISSIONS.WRITE)


class AppModel(PermissionsMixin, models.Model):
    """
    Base model for all permyt-mcp models.

    Provides UUID primary key, created/updated timestamps with user tracking,
    and permission checks via the manager.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(app_label)s_%(class)s_created_by",
        null=True,
        blank=True,
        on_delete=models.SET(set_delete_user),
    )

    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(app_label)s_%(class)s_updated_by",
        null=True,
        blank=True,
        on_delete=models.SET(set_delete_user),
    )

    objects = SuperuserManager()

    class Meta:
        abstract = True
        ordering = ("-created_at",)

    def __str__(self):
        return str(self.pk)

    @classmethod
    def get(cls, uuid):
        try:
            return cls.objects.get(pk=uuid)
        except ObjectDoesNotExist:
            return None

    def save(self, *args, **kwargs):
        user = get_current_user()
        if not self.created_at:
            self.created_by = user
        self.updated_by = user
        super().save(*args, **kwargs)
