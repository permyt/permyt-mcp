import factory
from factory.django import DjangoModelFactory

from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session

from .authtoken.models import Token
from .models import User, LoginToken


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user-{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@test.local")
    password = factory.PostGenerationMethodCall("set_password", "testpass123")


class TokenFactory(DjangoModelFactory):
    class Meta:
        model = Token

    user = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"token-{n}")


class LoginTokenFactory(DjangoModelFactory):
    class Meta:
        model = LoginToken

    token = factory.Sequence(lambda n: f"login-token-{n}")

    @factory.lazy_attribute
    def session(self):
        s = SessionStore()
        s.create()
        return Session.objects.get(session_key=s.session_key)
