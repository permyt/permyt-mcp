"""
Tests for the REST API views.
"""

import uuid
from unittest.mock import patch, MagicMock

import pytest
from rest_framework.test import APIClient
from app.core.users.authtoken.models import Token
from app.core.users.factories import UserFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def authenticated_user(db):
    user = UserFactory(permyt_user_id=uuid.uuid4())
    token = Token.objects.create(user=user, name="test")
    return user, token


@pytest.fixture
def auth_client(api_client, authenticated_user):
    user, token = authenticated_user
    api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return api_client, user


class TestRequestAccessView:
    @pytest.mark.django_db
    def test_unauthenticated_rejected(self, api_client):
        response = api_client.post(
            "/rest/requests/access/",
            {"description": "read mission log"},
            format="json",
        )
        assert response.status_code == 401

    @pytest.mark.django_db
    def test_missing_description_rejected(self, auth_client):
        client, _ = auth_client
        response = client.post("/rest/requests/access/", {}, format="json")
        assert response.status_code == 400

    @pytest.mark.django_db
    def test_user_without_permyt_id_rejected(self, api_client, db):
        user = UserFactory(permyt_user_id=None)
        token, _ = Token.objects.get_or_create(user=user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = api_client.post(
            "/rest/requests/access/",
            {"description": "read data"},
            format="json",
        )
        assert response.status_code == 400
        assert "permyt_user_id" in response.data["error"]

    @pytest.mark.django_db
    @patch("app.core.requests.views.PermytClient")
    def test_successful_request(self, MockClient, auth_client):
        client, user = auth_client
        mock_instance = MockClient.return_value
        mock_instance.request_access.return_value = {
            "request_id": "req-123",
            "status": "pending",
        }

        response = client.post(
            "/rest/requests/access/",
            {"description": "read mission log"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["request_id"] == "req-123"
        assert response.data["status"] == "pending"


class TestCheckAccessView:
    @pytest.mark.django_db
    def test_unauthenticated_rejected(self, api_client):
        response = api_client.post(
            "/rest/requests/status/",
            {"request_id": "req-123"},
            format="json",
        )
        assert response.status_code == 401

    @pytest.mark.django_db
    @patch("app.core.requests.views.PermytClient")
    def test_pending_status(self, MockClient, auth_client):
        client, _ = auth_client
        mock_instance = MockClient.return_value
        mock_instance.check_access.return_value = {
            "request_id": "req-123",
            "status": "pending",
        }

        response = client.post(
            "/rest/requests/status/",
            {"request_id": "req-123"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["status"] == "pending"

    @pytest.mark.django_db
    @patch("app.core.requests.views.PermytClient")
    def test_approved_calls_services(self, MockClient, auth_client):
        client, _ = auth_client
        mock_instance = MockClient.return_value
        mock_instance.check_access.return_value = {
            "request_id": "req-123",
            "status": "approved",
            "services": [{"encrypted_token": "...", "endpoints": []}],
        }
        mock_instance.call_services.return_value = [{"mission_log": "Day 1..."}]

        response = client.post(
            "/rest/requests/status/",
            {"request_id": "req-123"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["status"] == "completed"
        assert response.data["data"] == [{"mission_log": "Day 1..."}]


class TestPermytInboundView:
    @pytest.mark.django_db
    @patch("app.core.requests.views.PermytClient")
    def test_inbound_webhook(self, MockClient, api_client):
        mock_instance = MockClient.return_value
        mock_instance.handle_inbound.return_value = {"received": True}

        response = api_client.post(
            "/rest/permyt/inbound/",
            {"action": "request_status", "payload": {}, "proof": "..."},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["received"] is True
