import json

from secured_fields.fernet import get_fernet
from secured_fields.fields import EncryptedJSONField as _EncryptedJSONField

from django.db import models

from app.utils.encoders import JSONEncoder


class AppFieldMixin:
    """Adds default blank=null behavior to fields."""

    track: bool = True

    def __init__(self, *args, track: bool = True, **kwargs) -> None:
        kwargs.setdefault("blank", kwargs.get("null", False))
        super().__init__(*args, **kwargs)
        self.track = track


class BooleanField(AppFieldMixin, models.BooleanField):
    pass


class CharField(AppFieldMixin, models.CharField):
    pass


class DateTimeField(AppFieldMixin, models.DateTimeField):
    pass


class EmailField(AppFieldMixin, models.EmailField):
    pass


class ForeignKey(AppFieldMixin, models.ForeignKey):
    pass


class JSONField(AppFieldMixin, models.JSONField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("encoder", JSONEncoder)
        kwargs.setdefault("blank", True)
        super().__init__(*args, **kwargs)


class EncryptedJSONField(AppFieldMixin, _EncryptedJSONField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("encoder", JSONEncoder)
        kwargs.setdefault("blank", True)
        super().__init__(*args, **kwargs)

    def get_db_prep_save(self, value, connection):
        if value is None:
            return None
        json_bytes = json.dumps(value, cls=self.encoder or JSONEncoder).encode()
        return get_fernet().encrypt(json_bytes).decode()


class TextField(AppFieldMixin, models.TextField):
    pass


class UUIDField(AppFieldMixin, models.UUIDField):
    pass
