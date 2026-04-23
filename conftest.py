"""Root conftest -- shared fixtures for the PERMYT MCP test suite."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.users.factories import UserFactory


@pytest.fixture
def user(db):
    """A pre-created user for testing."""
    return UserFactory()


@pytest.fixture
def mock_permyt_client():
    """Create a PermytClient with mocked key loading (no real keys needed)."""
    with patch("app.core.requests.client.Path") as mock_path:
        mock_path.return_value.read_text.return_value = "mock-key"
        with patch("permyt.PermytClient.__init__", return_value=None):
            from app.core.requests.client import PermytClient

            client = PermytClient()
            client.private_key = MagicMock()
            client.host = "http://localhost:8000"
            client.service_id = "test-service-id"
            yield client
