"""Tests for MCP server tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.mcp.server import (
    permyt_request_access,
    permyt_check_access,
    permyt_view_scopes,
    _get_user_from_context,
)


@pytest.fixture
def mock_client_and_user():
    """Return a mock (PermytClient, User) pair."""
    client = MagicMock()
    user = MagicMock()
    user.permyt_user_id = "test-user-id"
    return client, user


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


class TestPermytCheckAccess:
    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_intermediate_status_includes_message(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.check_access.return_value = {"request_id": "req-1", "status": "awaiting"}

        result = await permyt_check_access("req-1", ctx=MagicMock())
        data = json.loads(result)
        assert data["status"] == "awaiting"
        assert "message" in data
        assert "Poll again" in data["message"]

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_completed_calls_services(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.check_access.return_value = {
            "request_id": "req-1",
            "status": "completed",
            "services": [{"endpoint": "..."}],
        }
        client.call_services.return_value = [{"data": "user notes"}]

        result = await permyt_check_access("req-1", ctx=MagicMock())
        data = json.loads(result)
        assert data["status"] == "completed"
        assert data["data"] == [{"data": "user notes"}]

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_service_error_returns_generic_message(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.check_access.return_value = {
            "request_id": "req-1",
            "status": "completed",
            "services": [{"endpoint": "..."}],
        }
        client.call_services.side_effect = RuntimeError("connection refused")

        result = await permyt_check_access("req-1", ctx=MagicMock())
        data = json.loads(result)
        assert data["status"] == "error"
        assert "connection refused" not in data["message"]

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_rejected_includes_failure_message(self, mock_get_user, mock_client_and_user):
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

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_incomplete_includes_failure_message(self, mock_get_user, mock_client_and_user):
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
        assert "more detailed description" in data["message"]


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
    async def test_error_returns_generic_message(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.view_scopes.side_effect = RuntimeError("connection refused")

        result = await permyt_view_scopes(ctx=MagicMock())
        data = json.loads(result)
        assert data["status"] == "error"
        assert "connection refused" not in data["message"]


class TestGetUserFromContext:
    @pytest.mark.asyncio
    async def test_no_auth_token_raises(self):
        ctx = MagicMock()
        ctx.request_context.request = None
        with pytest.raises(ValueError, match="No auth token found"):
            await _get_user_from_context(ctx)
