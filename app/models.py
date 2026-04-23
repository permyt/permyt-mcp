"""
This file replaces the default django.db.models.

It imports the default django models and overrides with custom fields and models.

Usage:
    from app import models

    class MyClass(models.AppModel):
        name = models.CharField(max_length=256)
"""

from secured_fields.fields import *  # pylint: disable=wildcard-import, unused-wildcard-import
from django.db.models import *  # pylint: disable=wildcard-import, unused-wildcard-import
from app.mixins.models import AppModel  # pylint: disable=unused-import
from app.utils.fields import *  # pylint: disable=wildcard-import, unused-wildcard-import
