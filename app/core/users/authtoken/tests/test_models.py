"""Tests for the Token model."""

import pytest

from app.core.users.authtoken.models import Token
from app.core.users.factories import UserFactory


class TestTokenModel:
    @pytest.mark.django_db
    def test_auto_generates_key(self):
        user = UserFactory()
        token = Token.objects.create(user=user, name="test")
        assert token.key
        assert len(token.key) > 20

    @pytest.mark.django_db
    def test_key_is_unique(self):
        user = UserFactory()
        t1 = Token.objects.create(user=user, name="first")
        t2 = Token.objects.create(user=user, name="second")
        assert t1.key != t2.key

    @pytest.mark.django_db
    def test_hidden_key_masks_correctly(self):
        user = UserFactory()
        token = Token.objects.create(user=user, name="test")
        hidden = token.hidden_key
        # Should show only last 4 chars, rest masked
        assert hidden.endswith(token.key[-4:])
        assert "*" in hidden

    @pytest.mark.django_db
    def test_str_representation(self):
        user = UserFactory()
        token = Token.objects.create(user=user, name="my-key")
        assert "my-key" in str(token)
