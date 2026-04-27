"""
Tests for the REST API views.
"""

import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from app.core.requests.models import PendingServiceCall
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


def _service_credential(expires_at):
    return {
        "request_id": "req-123",
        "encrypted_token": "ciphertext",
        "endpoints": [
            {
                "url": "https://provider.example/api/x",
                "description": "Send a payment",
                "input_fields": {"account": "IBAN", "value": "Amount"},
            }
        ],
        "expires_at": expires_at.isoformat(),
        "public_key": "----- PUBLIC -----",
    }


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
    def test_completed_returns_endpoint_schema_and_does_not_auto_call(
        self, MockClient, auth_client
    ):
        client, user = auth_client
        mock_instance = MockClient.return_value
        services = [_service_credential(timezone.now() + timedelta(minutes=5))]
        mock_instance.check_access.return_value = {
            "request_id": "req-123",
            "status": "completed",
            "services": services,
        }

        response = client.post(
            "/rest/requests/status/",
            {"request_id": "req-123"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["status"] == "completed"
        assert response.data["next_action"] == "/rest/requests/call/"
        assert response.data["endpoints"] == [
            {
                "description": "Send a payment",
                "input_fields": {"account": "IBAN", "value": "Amount"},
            }
        ]
        mock_instance.call_services.assert_not_called()
        assert PendingServiceCall.objects.filter(request_id="req-123", user=user).exists()


class TestCallServiceView:
    @pytest.mark.django_db
    def test_unauthenticated_rejected(self, api_client):
        response = api_client.post(
            "/rest/requests/call/",
            {"request_id": "req-123", "inputs": {}},
            format="json",
        )
        assert response.status_code == 401

    @pytest.mark.django_db
    @patch("app.core.requests.views.PermytClient")
    def test_executes_with_dynamic_inputs_and_marks_consumed(self, MockClient, auth_client):
        client, user = auth_client
        services = [_service_credential(timezone.now() + timedelta(minutes=5))]
        PendingServiceCall.objects.create(
            request_id="req-123",
            user=user,
            services=services,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        mock_instance = MockClient.return_value
        mock_instance.call_services.return_value = [{"payment.send": {"ok": True}}]

        inputs = {"account": "PT50…", "value": "50.00"}
        response = client.post(
            "/rest/requests/call/",
            {"request_id": "req-123", "inputs": inputs},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["status"] == "completed"
        assert response.data["data"] == [{"scope": "payment.send", "data": {"ok": True}}]
        mock_instance.set_endpoint_inputs.assert_called_once_with(inputs)
        mock_instance.call_services.assert_called_once_with(services)

        pending = PendingServiceCall.objects.get(request_id="req-123")
        assert pending.consumed_at is not None

    @pytest.mark.django_db
    def test_unknown_request_returns_error(self, auth_client):
        client, _ = auth_client
        response = client.post(
            "/rest/requests/call/",
            {"request_id": "missing", "inputs": {}},
            format="json",
        )
        assert response.status_code == 400
        assert response.data["code"] == "unknown_request"

    @pytest.mark.django_db
    def test_already_consumed_rejected(self, auth_client):
        client, user = auth_client
        services = [_service_credential(timezone.now() + timedelta(minutes=5))]
        PendingServiceCall.objects.create(
            request_id="req-123",
            user=user,
            services=services,
            expires_at=timezone.now() + timedelta(minutes=5),
            consumed_at=timezone.now(),
        )
        response = client.post(
            "/rest/requests/call/",
            {"request_id": "req-123", "inputs": {}},
            format="json",
        )
        assert response.status_code == 400
        assert response.data["code"] == "already_consumed"


class TestViewScopesView:
    @pytest.mark.django_db
    def test_unauthenticated_rejected(self, api_client):
        response = api_client.post("/rest/requests/scopes/", format="json")
        assert response.status_code == 401

    @pytest.mark.django_db
    def test_user_without_permyt_id_rejected(self, api_client, db):
        user = UserFactory(permyt_user_id=None)
        token, _ = Token.objects.get_or_create(user=user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = api_client.post("/rest/requests/scopes/", format="json")
        assert response.status_code == 400
        assert "permyt_user_id" in response.data["error"]

    @pytest.mark.django_db
    @patch("app.core.requests.views.PermytClient")
    def test_successful_request(self, MockClient, auth_client):
        client, user = auth_client
        mock_instance = MockClient.return_value
        mock_instance.view_scopes.return_value = {
            "scopes": [
                {
                    "service_name": "NoteVault",
                    "service_description": "Secure notes",
                    "scopes": [{"reference": "notes.read", "name": "Read Notes"}],
                }
            ]
        }

        response = client.post("/rest/requests/scopes/", format="json")
        assert response.status_code == 200
        assert len(response.data["scopes"]) == 1
        assert response.data["scopes"][0]["service_name"] == "NoteVault"


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
