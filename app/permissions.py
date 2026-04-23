from typing import TypeAlias

from django.db.models import IntegerChoices


class Permission(IntegerChoices):
    READ = 1, "Read only"
    WRITE = 2, "Read and write"
    ADMIN = 3, "Administrator"
    OWNER = 4, "Owner"


PERMISSIONS = Permission
PermissionType: TypeAlias = int
