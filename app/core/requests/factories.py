import factory
from factory.django import DjangoModelFactory

from .models import Nonce


class NonceFactory(DjangoModelFactory):
    class Meta:
        model = Nonce

    value = factory.Sequence(lambda n: f"nonce-{n:032x}")
