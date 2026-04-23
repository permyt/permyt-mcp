import json
import logging

from typing import Any
from uuid import UUID

from rest_framework.utils.encoders import JSONEncoder as RestFrameworkJSONEncoder

from django.db.models import Model

logger = logging.getLogger("console")


class JSONEncoder(RestFrameworkJSONEncoder):
    """
    JSONEncoder subclass that knows how to encode instances, classes,
    date/time/timedelta, decimal types, generators and other basic python objects.
    """

    def default(self, obj: Any) -> Any:
        from django.contrib.contenttypes.models import ContentType

        if isinstance(obj, UUID):
            return str(obj)

        if isinstance(obj, type(Model)):
            return ContentType.objects.get_for_model(obj).id

        if isinstance(obj, Model):
            pk = obj.pk
            return pk if isinstance(pk, int) else str(pk)

        try:
            return super().default(obj)
        except Exception:
            return str(obj) if obj is not None else None

    @classmethod
    def dumps(cls, obj):
        return cls().encode(obj)

    @classmethod
    def loads(cls, obj):
        return json.loads(obj)

    @classmethod
    def force_encoding(cls, obj):
        return json.loads(json.dumps(obj, cls=JSONEncoder))


def log_formatted_json(data: Any, indent=2) -> None:
    logger.info(json.dumps(data, indent=indent, cls=JSONEncoder))
