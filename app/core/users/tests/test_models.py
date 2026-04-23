"""Tests for the LoginToken model."""

import pytest
from django.contrib.sessions.backends.db import SessionStore

from app.core.users.factories import UserFactory, LoginTokenFactory
from app.core.users.models import LoginToken


class TestLoginTokenLogin:
    @pytest.fixture
    def login_token(self, db):
        return LoginTokenFactory()

    @pytest.mark.django_db
    def test_login_marks_token_used(self, login_token):
        user = UserFactory()
        login_token.login(user)
        login_token.refresh_from_db()
        assert login_token.logged_in is True
        assert login_token.user == user

    @pytest.mark.django_db
    def test_login_rejects_already_used(self, login_token):
        user = UserFactory()
        login_token.login(user)
        with pytest.raises(ValueError, match="already been used"):
            login_token.login(user)

    @pytest.mark.django_db
    def test_login_rejects_different_user(self, db):
        user_a = UserFactory()
        user_b = UserFactory()
        token = LoginTokenFactory(user=user_a)
        with pytest.raises(ValueError, match="different user"):
            token.login(user_b)


class TestLoginTokenStr:
    @pytest.mark.django_db
    def test_str_representation(self):
        token = LoginTokenFactory()
        result = str(token)
        assert "LoginToken" in result
