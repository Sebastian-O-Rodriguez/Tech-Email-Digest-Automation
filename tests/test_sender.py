"""Tests for send_digest in sender.py."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from email_ingester.config import Config
from email_ingester.models import DigestOutput
from email_ingester.sender import SendError, send_digest


def _make_config() -> Config:
    return Config(
        azure_tenant_id="tenant-id",
        azure_client_id="client-id",
        azure_client_secret="client-secret",
        mailbox_user_id="user@example.com",
        mailbox_folder="Inbox",
        openrouter_api_key="sk-test",
        llm_model="claude-sonnet-4-6-20250514",
        digest_recipient="recipient@example.com",
        state_file="state.json",
    )


def _make_digest() -> DigestOutput:
    from email_ingester.models import DigestReport

    return DigestOutput(
        generated_at=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
        total_processed=1,
        report=DigestReport(breaking_news="Test", tech_stacks="", new_software="", deep_dives=""),
        html="<html><body>Digest content</body></html>",
    )


def _mock_response(status_code: int, text: str = "", is_success: bool | None = None) -> MagicMock:
    """Build a mock httpx.Response with configurable status_code, text, and is_success."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text
    # Allow explicit override; default to True for 2xx
    if is_success is None:
        response.is_success = 200 <= status_code < 300
    else:
        response.is_success = is_success
    return response


class TestSendDigestSuccess:
    def test_successful_send_returns_none(self):
        """202 Accepted from Graph API — no exception raised."""
        config = _make_config()
        digest = _make_digest()

        with patch("email_ingester.sender.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(202, is_success=True)
            result = send_digest(config, "bearer-token", digest)

        assert result is None

    def test_successful_send_calls_correct_url(self):
        """POST is made to the correct Graph API endpoint."""
        config = _make_config()
        digest = _make_digest()

        with patch("email_ingester.sender.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(202, is_success=True)
            send_digest(config, "bearer-token", digest)

        called_url = mock_post.call_args[0][0]
        assert "graph.microsoft.com" in called_url
        assert config.mailbox_user_id in called_url
        assert "sendMail" in called_url


class TestSendDigestNetworkErrors:
    def test_network_error_raises_send_error(self):
        """httpx.NetworkError is wrapped in SendError."""
        config = _make_config()
        digest = _make_digest()

        with patch("email_ingester.sender.httpx.post") as mock_post:
            mock_post.side_effect = httpx.NetworkError("connection refused")
            with pytest.raises(SendError):
                send_digest(config, "bearer-token", digest)

    def test_timeout_raises_send_error(self):
        """httpx.TimeoutException is wrapped in SendError."""
        config = _make_config()
        digest = _make_digest()

        with patch("email_ingester.sender.httpx.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("timed out")
            with pytest.raises(SendError):
                send_digest(config, "bearer-token", digest)


class TestSendDigestHttpErrors:
    def test_401_raises_send_error_with_status_code(self):
        """401 Unauthorized raises SendError with status_code=401."""
        config = _make_config()
        digest = _make_digest()

        with patch("email_ingester.sender.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(401, text="Unauthorized")
            with pytest.raises(SendError) as exc_info:
                send_digest(config, "bearer-token", digest)

        assert exc_info.value.status_code == 401
        assert "Authentication failed" in str(exc_info.value)

    def test_429_raises_send_error_with_status_code(self):
        """429 Too Many Requests raises SendError with status_code=429."""
        config = _make_config()
        digest = _make_digest()

        with patch("email_ingester.sender.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(429, text="Too Many Requests")
            with pytest.raises(SendError) as exc_info:
                send_digest(config, "bearer-token", digest)

        assert exc_info.value.status_code == 429
        assert "Rate limited" in str(exc_info.value)

    def test_500_raises_send_error_with_status_code(self):
        """500 Internal Server Error raises SendError with status_code=500."""
        config = _make_config()
        digest = _make_digest()

        with patch("email_ingester.sender.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(500, text="Internal Server Error")
            with pytest.raises(SendError) as exc_info:
                send_digest(config, "bearer-token", digest)

        assert exc_info.value.status_code == 500

    def test_403_raises_send_error_with_permission_message(self):
        """403 Forbidden raises SendError with 'Permission denied' in message."""
        config = _make_config()
        digest = _make_digest()

        with patch("email_ingester.sender.httpx.post") as mock_post:
            mock_post.return_value = _mock_response(403, text="Forbidden")
            with pytest.raises(SendError) as exc_info:
                send_digest(config, "bearer-token", digest)

        assert exc_info.value.status_code == 403
        assert "Permission denied" in str(exc_info.value)
