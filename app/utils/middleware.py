from __future__ import annotations

from threading import local
from typing import Callable
from uuid import UUID

from django.conf import settings
from django.contrib.auth.models import AbstractUser

USER_ATTR_NAME = getattr(settings, "LOCAL_USER_ATTR_NAME", "_current_user_uuid")
_thread_locals = local()


class ThreadLocalUserMiddleware:
    """Sets the request user as the user executing the local thread."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        with SetCurrentUser(user):
            response = self.get_response(request)
        return response


class SetCurrentUser:
    """
    Context manager to set the user in a local thread.

    Usage:
        with SetCurrentUser(user):
            do_some_action_as_this_user
    """

    def __init__(
        self, user: AbstractUser | UUID | str | None, keep_prev_user_on_exit: bool = False
    ):
        from app.core.users.models import User

        if isinstance(user, User):
            self.user = user
        elif isinstance(user, (str, UUID)):
            self.user = User.objects.filter(pk=str(user)).last()
        else:
            self.user = None

        self._keep_prev_user_on_exit = keep_prev_user_on_exit
        if settings.TEST or keep_prev_user_on_exit:
            self._previous_user = get_current_user()

    def __enter__(self):
        self._set_current_user(lambda _: self.user)
        return self.user

    def __exit__(self, *args, **kwargs):
        if settings.TEST or self._keep_prev_user_on_exit:
            self._set_current_user(lambda _: self._previous_user)
        else:
            self._set_current_user(lambda _: None)

    def _set_current_user(self, user_fun: Callable[..., AbstractUser]):
        setattr(_thread_locals, USER_ATTR_NAME, user_fun.__get__(user_fun, local))


def get_current_user() -> AbstractUser | None:
    current_user = getattr(_thread_locals, USER_ATTR_NAME, None)
    if callable(current_user):
        current_user = current_user()
    return current_user
