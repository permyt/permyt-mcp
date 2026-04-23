from __future__ import annotations

from django.db.models import Manager, QuerySet

from .permissions import PERMISSIONS, PermissionType


class BaseManager(Manager):
    """
    Base Manager containing all common methods for all managers.
    """

    def __init__(
        self,
        *args,
        public: bool = False,
        allow_guests: bool = False,
        only_superusers_can_create: bool = False,
        superuser_field: list[str] | str = "is_superuser",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.only_superusers_can_create = only_superusers_can_create
        self._superuser_field = (
            [superuser_field] if isinstance(superuser_field, str) else superuser_field
        )
        self._public = public
        self._allow_guests = allow_guests

    def with_permission(self, user, permission: PermissionType, **kwargs) -> QuerySet:
        raise NotImplementedError(f"`with_permission` is not defined in {self.__class__.__name__}")

    def as_reader(self, user, **kwargs) -> QuerySet:
        return self.with_permission(user, PERMISSIONS.READ, **kwargs)

    def as_writer(self, user, **kwargs) -> QuerySet:
        kwargs.setdefault("as_superuser", True)
        return self.with_permission(user, PERMISSIONS.WRITE, **kwargs)

    def as_admin(self, user, **kwargs) -> QuerySet:
        kwargs.setdefault("as_superuser", True)
        return self.with_permission(user, PERMISSIONS.ADMIN, **kwargs)

    def as_owner(self, user, **kwargs) -> QuerySet:
        return self.with_permission(user, PERMISSIONS.OWNER, **kwargs)

    def check_object_permission(self, obj, user, permission) -> bool:
        raise NotImplementedError(
            f"`check_object_permission` is not defined in {self.__class__.__name__}"
        )

    def is_superuser(self, user) -> bool:
        return user.is_superuser or any(
            getattr(user, field, False) for field in self._superuser_field
        )

    def can_create(self, user) -> bool:
        return user.is_authenticated and (
            not self.only_superusers_can_create or self.is_superuser(user)
        )


class SuperuserManager(BaseManager):
    """Only superusers can create/change; optionally public for reads."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("only_superusers_can_create", True)
        kwargs.setdefault("public", False)
        super().__init__(*args, **kwargs)

    def with_permission(self, user, permission: PermissionType, **kwargs) -> QuerySet:
        if (self._public and permission == PERMISSIONS.READ) or self.is_superuser(user):
            return self.get_queryset()
        return self.get_queryset().none()

    def check_object_permission(self, obj, user, permission) -> bool:
        return self.is_superuser(user) or (self._public and permission == PERMISSIONS.READ)


class OwnerManager(SuperuserManager):
    """Only owner (creator) and superusers can edit or delete."""

    def __init__(self, *args, field: str = "created_by", **kwargs):
        kwargs.setdefault("only_superusers_can_create", False)
        kwargs.setdefault("public", False)
        self._field = field
        super().__init__(*args, **kwargs)

    def with_permission(
        self, user, permission: PermissionType, as_superuser=False, **kwargs
    ) -> QuerySet:
        if (permission == PERMISSIONS.READ and self._public) or (
            as_superuser and self.is_superuser(user)
        ):
            return self.get_queryset()
        return self.get_queryset().filter(**{self._field: user.pk})

    def check_object_permission(self, obj, user, permission) -> bool:
        if (permission == PERMISSIONS.READ and self._public) or self.is_superuser(user):
            return True
        model = obj.__class__
        return model.objects.with_permission(user, permission).filter(id=obj.id).exists()
