"""
Tests for the requester PermytClient contract.

Exercises the client's abstract-method implementations:
* Nonce replay protection (atomic insert)
* _prepare_data_for_endpoint (returns empty dict)
"""

from datetime import datetime, timedelta, timezone

import pytest

from permyt.exceptions import ExpiredRequestError


@pytest.mark.django_db
class TestNonceAndTimestamp:
    def test_fresh_nonce_accepted(self, mock_permyt_client):
        mock_permyt_client._validate_nonce_and_timestamp(
            "nonce-1", datetime.now(timezone.utc).isoformat()
        )

    def test_nonce_reuse_rejected(self, mock_permyt_client):
        ts = datetime.now(timezone.utc).isoformat()
        mock_permyt_client._validate_nonce_and_timestamp("nonce-2", ts)
        with pytest.raises(ExpiredRequestError, match="Nonce"):
            mock_permyt_client._validate_nonce_and_timestamp("nonce-2", ts)

    def test_expired_timestamp_rejected(self, mock_permyt_client):
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with pytest.raises(ExpiredRequestError, match="timestamp"):
            mock_permyt_client._validate_nonce_and_timestamp("nonce-old", old)

    def test_future_timestamp_rejected(self, mock_permyt_client):
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        with pytest.raises(ExpiredRequestError, match="timestamp"):
            mock_permyt_client._validate_nonce_and_timestamp("nonce-future", future)


class TestPrepareDataForEndpoint:
    def test_returns_empty_dict(self, mock_permyt_client):
        result = mock_permyt_client._prepare_data_for_endpoint(
            "req-123", {"url": "http://provider/api/something", "scope": "test"}
        )
        assert result == {}
