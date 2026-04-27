"""Tests for MCP server tools."""

import json
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from app.core.requests.models import PendingServiceCall
from app.core.requests.responses import flatten_service_data
from app.core.users.factories import UserFactory
from app.mcp.server import (
    _get_user_from_context,
    permyt_call_service,
    permyt_check_access,
    permyt_request_access,
    permyt_view_scopes,
)


@pytest.fixture
def mock_client_and_user(transactional_db):
    """Return (mock_client, real_user) so PendingServiceCall lookups can resolve.

    ``transactional_db`` (rather than ``db``) is required because the async
    tools cross thread boundaries via ``asyncio.to_thread``; sqlite's
    transaction-scoped locks otherwise deadlock between the test thread and
    the worker.
    """
    client = MagicMock()
    user = UserFactory(permyt_user_id=uuid.uuid4())
    return client, user


def _service_credential(expires_at, endpoints=None):
    return {
        "request_id": "req-1",
        "encrypted_token": "ciphertext",
        "endpoints": endpoints
        or [
            {
                "url": "https://provider.example/api/x",
                "description": "Send a payment",
                "input_fields": {
                    "account": "Beneficiary IBAN",
                    "value": "Amount",
                    "currency": "ISO 4217 code",
                },
            }
        ],
        "expires_at": expires_at.isoformat(),
        "public_key": "----- PUBLIC -----",
    }


class TestPermytRequestAccess:
    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_returns_json_with_request_id(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.request_access.return_value = {"request_id": "req-1", "status": "pending"}

        result = await permyt_request_access("read mission log", ctx=MagicMock())
        data = json.loads(result)

        assert data["request_id"] == "req-1"
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_transport_error_is_retryable(self, mock_get_user, mock_client_and_user):
        from permyt.exceptions import TransportError

        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.request_access.side_effect = TransportError("broker timeout")

        result = await permyt_request_access("hi", ctx=MagicMock())
        data = json.loads(result)

        assert data["status"] == "error"
        assert data["code"] == "transport_error"
        assert data["retryable"] is True


class TestPermytCheckAccess:
    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_intermediate_status_has_clean_message_and_client_hint(
        self, mock_get_user, mock_client_and_user
    ):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.check_access.return_value = {"request_id": "req-1", "status": "awaiting"}

        result = await permyt_check_access("req-1", ctx=MagicMock())
        data = json.loads(result)

        assert data["status"] == "awaiting"
        assert "message" in data
        assert "client_hint" in data
        assert "permyt_check_access" in data["client_hint"]

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_completed_returns_endpoint_schema_and_does_not_auto_call(
        self, mock_get_user, mock_client_and_user
    ):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        services = [_service_credential(timezone.now() + timedelta(minutes=5))]
        client.check_access.return_value = {
            "request_id": "req-1",
            "status": "completed",
            "services": services,
        }

        result = await permyt_check_access("req-1", ctx=MagicMock())
        data = json.loads(result)

        assert data["status"] == "completed"
        assert data["next_action"] == "permyt_call_service"
        assert data["endpoints"] == [
            {
                "description": "Send a payment",
                "input_fields": {
                    "account": "Beneficiary IBAN",
                    "value": "Amount",
                    "currency": "ISO 4217 code",
                },
            }
        ]
        client.call_services.assert_not_called()
        # Pending row was created so call_service can later execute
        exists = await sync_to_async(
            lambda: PendingServiceCall.objects.filter(request_id="req-1", user=user).exists()
        )()
        assert exists

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_completed_is_idempotent_on_repeat_polls(
        self, mock_get_user, mock_client_and_user
    ):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        services = [_service_credential(timezone.now() + timedelta(minutes=5))]
        client.check_access.return_value = {
            "request_id": "req-1",
            "status": "completed",
            "services": services,
        }

        await permyt_check_access("req-1", ctx=MagicMock())
        await permyt_check_access("req-1", ctx=MagicMock())

        count = await sync_to_async(
            lambda: PendingServiceCall.objects.filter(request_id="req-1", user=user).count()
        )()
        assert count == 1

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_check_access_transient_error_is_retryable(
        self, mock_get_user, mock_client_and_user
    ):
        from permyt.exceptions import TransportError

        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.check_access.side_effect = TransportError("broker 503")

        result = await permyt_check_access("req-1", ctx=MagicMock())
        data = json.loads(result)
        assert data["status"] == "error"
        assert data["retryable"] is True

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_rejected_has_separate_message_and_client_hint(
        self, mock_get_user, mock_client_and_user
    ):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.check_access.return_value = {
            "request_id": "req-1",
            "status": "rejected",
            "reason": "user denied",
        }

        result = await permyt_check_access("req-1", ctx=MagicMock())
        data = json.loads(result)

        assert data["status"] == "rejected"
        assert data["reason"] == "user denied"
        assert "denied" in data["message"]
        assert "Do not retry" in data["client_hint"]

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_incomplete_has_separate_message_and_client_hint(
        self, mock_get_user, mock_client_and_user
    ):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.check_access.return_value = {
            "request_id": "req-1",
            "status": "incomplete",
            "reason": "missing account details",
        }

        result = await permyt_check_access("req-1", ctx=MagicMock())
        data = json.loads(result)

        assert data["status"] == "incomplete"
        assert "too vague" in data["message"]
        assert "clarify" in data["client_hint"]


class TestPermytCallService:
    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_executes_with_dynamic_inputs_and_marks_consumed(
        self, mock_get_user, mock_client_and_user
    ):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)

        services = [_service_credential(timezone.now() + timedelta(minutes=5))]
        await sync_to_async(PendingServiceCall.objects.create)(
            request_id="req-1",
            user=user,
            services=services,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        client.call_services.return_value = [{"payment.send": {"ok": True, "tx_id": "x123"}}]

        inputs = {"account": "PT50…", "value": "50.00", "currency": "EUR"}
        result = await permyt_call_service("req-1", inputs=inputs, ctx=MagicMock())
        data = json.loads(result)

        assert data["status"] == "completed"
        assert data["data"] == [{"scope": "payment.send", "data": {"ok": True, "tx_id": "x123"}}]
        client.set_endpoint_inputs.assert_called_once_with(inputs)
        client.call_services.assert_called_once_with(services)

        pending = await sync_to_async(PendingServiceCall.objects.get)(request_id="req-1")
        assert pending.consumed_at is not None

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_unknown_request_returns_error(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)

        result = await permyt_call_service("missing", inputs={}, ctx=MagicMock())
        data = json.loads(result)

        assert data["status"] == "error"
        assert data["code"] == "unknown_request"
        client.call_services.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_already_consumed_rejected(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)

        services = [_service_credential(timezone.now() + timedelta(minutes=5))]
        await sync_to_async(PendingServiceCall.objects.create)(
            request_id="req-1",
            user=user,
            services=services,
            expires_at=timezone.now() + timedelta(minutes=5),
            consumed_at=timezone.now(),
        )

        result = await permyt_call_service("req-1", inputs={}, ctx=MagicMock())
        data = json.loads(result)

        assert data["code"] == "already_consumed"
        client.call_services.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_expired_pending_rejected(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)

        services = [_service_credential(timezone.now() - timedelta(minutes=1))]
        await sync_to_async(PendingServiceCall.objects.create)(
            request_id="req-1",
            user=user,
            services=services,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        result = await permyt_call_service("req-1", inputs={}, ctx=MagicMock())
        data = json.loads(result)

        assert data["code"] == "expired"
        client.call_services.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_provider_transport_error_is_retryable(self, mock_get_user, mock_client_and_user):
        from permyt.exceptions import TransportError

        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        services = [_service_credential(timezone.now() + timedelta(minutes=5))]
        await sync_to_async(PendingServiceCall.objects.create)(
            request_id="req-1",
            user=user,
            services=services,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        client.call_services.side_effect = TransportError("provider 503")

        result = await permyt_call_service("req-1", inputs={}, ctx=MagicMock())
        data = json.loads(result)
        assert data["status"] == "error"
        assert data["retryable"] is True


class TestPermytViewScopes:
    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_returns_scopes(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.view_scopes.return_value = {
            "scopes": [
                {
                    "service_name": "NoteVault",
                    "service_description": "Secure note storage",
                    "scopes": [
                        {
                            "reference": "notes.read",
                            "name": "Read Notes",
                            "description": "Read user notes",
                            "inputs": [],
                        }
                    ],
                }
            ]
        }

        result = await permyt_view_scopes(ctx=MagicMock())
        data = json.loads(result)

        assert len(data["scopes"]) == 1
        assert data["scopes"][0]["service_name"] == "NoteVault"
        assert data["scopes"][0]["scopes"][0]["reference"] == "notes.read"

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_error_returns_envelope(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.view_scopes.side_effect = RuntimeError("connection refused")

        result = await permyt_view_scopes(ctx=MagicMock())
        data = json.loads(result)
        assert data["status"] == "error"
        # Generic exceptions stay opaque (no internal message leaked)
        assert "connection refused" not in data["message"]


class TestGetUserFromContext:
    @pytest.mark.asyncio
    async def test_no_auth_token_raises(self):
        ctx = MagicMock()
        ctx.request_context.request = None
        with pytest.raises(ValueError, match="No auth token found"):
            await _get_user_from_context(ctx)


class TestFlattenServiceData:
    def test_flattens_scope_dict(self):
        raw = [{"notes.read": {"crew_notes": "secret"}}]
        assert flatten_service_data(raw) == [
            {"scope": "notes.read", "data": {"crew_notes": "secret"}}
        ]

    def test_flattens_multi_scope_dict(self):
        raw = [{"notes.read": {"notes": "a"}, "notes.write": {"result": "ok"}}]
        result = flatten_service_data(raw)
        assert len(result) == 2
        assert {"scope": "notes.read", "data": {"notes": "a"}} in result
        assert {"scope": "notes.write", "data": {"result": "ok"}} in result

    def test_passes_through_non_dict_items(self):
        raw = ["plain string", 42]
        assert flatten_service_data(raw) == ["plain string", 42]

    def test_empty_list(self):
        assert flatten_service_data([]) == []

    def test_mixed_items(self):
        raw = [{"scope.a": "data_a"}, "not a dict"]
        result = flatten_service_data(raw)
        assert result == [{"scope": "scope.a", "data": "data_a"}, "not a dict"]
