"""Tests for auth token views (login, logout, token CRUD)."""

import pytest
from rest_framework.test import APIClient

from app.core.users.authtoken.models import Token
from app.core.users.factories import UserFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_with_password(db):
    user = UserFactory()
    user.set_password("testpass123")
    user.save()
    return user


class TestLoginView:
    @pytest.mark.django_db
    def test_login_returns_token(self, api_client, user_with_password):
        response = api_client.post(
            "/rest/auth/token/login/",
            {"username": user_with_password.email, "password": "testpass123"},
            format="json",
        )
        assert response.status_code == 200
        assert "token" in response.data
        assert Token.objects.filter(user=user_with_password, system=True).exists()

    @pytest.mark.django_db
    def test_login_invalid_credentials(self, api_client, user_with_password):
        response = api_client.post(
            "/rest/auth/token/login/",
            {"username": user_with_password.email, "password": "wrong"},
            format="json",
        )
        assert response.status_code == 400

    @pytest.mark.django_db
    def test_login_missing_fields(self, api_client):
        response = api_client.post("/rest/auth/token/login/", {}, format="json")
        assert response.status_code == 400


class TestLogoutView:
    @pytest.mark.django_db
    def test_logout_requires_auth(self, api_client):
        response = api_client.post("/rest/auth/token/logout/", format="json")
        assert response.status_code == 401

    @pytest.mark.django_db
    def test_logout_authenticated(self, api_client, user_with_password):
        token = Token.objects.create(user=user_with_password, system=True)
        api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = api_client.post("/rest/auth/token/logout/", format="json")
        assert response.status_code == 200
        assert response.data["done"] is True


class TestTokenViewSet:
    @pytest.fixture
    def auth_client(self, api_client, user_with_password):
        token = Token.objects.create(user=user_with_password, system=True)
        api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return api_client

    @pytest.mark.django_db
    def test_create_token(self, auth_client):
        response = auth_client.post(
            "/rest/auth/token/",
            {"name": "my-api-key"},
            format="json",
        )
        assert response.status_code == 201
        assert "key" in response.data
        assert response.data["name"] == "my-api-key"

    @pytest.mark.django_db
    def test_list_tokens(self, auth_client, user_with_password):
        Token.objects.create(user=user_with_password, name="visible", system=False)
        Token.objects.create(user=user_with_password, name="system", system=True)
        response = auth_client.get("/rest/auth/token/", format="json")
        assert response.status_code == 200
        # Only non-system tokens are listed
        names = [t["name"] for t in response.data]
        assert "visible" in names
        assert "system" not in names

    @pytest.mark.django_db
    def test_delete_token(self, auth_client, user_with_password):
        token = Token.objects.create(user=user_with_password, name="to-delete", system=False)
        response = auth_client.delete(f"/rest/auth/token/{token.pk}/", format="json")
        assert response.status_code == 204
        assert not Token.objects.filter(pk=token.pk).exists()
