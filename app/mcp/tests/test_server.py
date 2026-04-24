"""Tests for MCP server tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.server import (
    permyt_request_access,
    permyt_check_access,
    permyt_request_and_fetch,
    _get_user_from_context,
)


def _make_async_ctx():
    """Create a mock Context with async info/report_progress methods."""
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.report_progress = AsyncMock()
    return ctx


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
    async def test_pending_status(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.check_access.return_value = {"request_id": "req-1", "status": "pending"}

        result = await permyt_check_access("req-1", ctx=MagicMock())
        data = json.loads(result)
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_approved_calls_services(self, mock_get_user, mock_client_and_user):
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
        # Should NOT contain the actual exception message
        assert "connection refused" not in data["error"]


class TestPermytRequestAndFetch:
    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_returns_timeout_on_pending(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.request_access.return_value = {"request_id": "req-1", "status": "pending"}
        client.check_access.return_value = {"request_id": "req-1", "status": "pending"}

        ctx = _make_async_ctx()
        result = await permyt_request_and_fetch("read log", max_wait_seconds=1, ctx=ctx)
        data = json.loads(result)
        assert data["status"] == "timeout"
        assert "message" in data

    @pytest.mark.asyncio
    @patch("app.mcp.server._get_user_from_context")
    async def test_returns_rejected(self, mock_get_user, mock_client_and_user):
        client, user = mock_client_and_user
        mock_get_user.return_value = (client, user)
        client.request_access.return_value = {"request_id": "req-1", "status": "pending"}
        client.check_access.return_value = {
            "request_id": "req-1",
            "status": "rejected",
            "reason": "user denied",
        }

        ctx = _make_async_ctx()
        result = await permyt_request_and_fetch("read log", max_wait_seconds=10, ctx=ctx)
        data = json.loads(result)
        assert data["status"] == "rejected"
        assert data["reason"] == "user denied"
        assert "message" in data


class TestGetUserFromContext:
    @pytest.mark.asyncio
    async def test_no_auth_token_raises(self):
        ctx = MagicMock()
        ctx.request_context.request = None
        with pytest.raises(ValueError, match="No auth token found"):
            await _get_user_from_context(ctx)
