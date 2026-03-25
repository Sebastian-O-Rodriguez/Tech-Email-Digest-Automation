"""Tests for auth.py — Graph token acquisition and error handling."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from email_ingester.auth import get_graph_token
from email_ingester.config import Config


def _make_config() -> Config:
    return Config(
        azure_tenant_id="test-tenant",
        azure_client_id="test-client-id",
        azure_client_secret="test-client-secret",
        mailbox_user_id="user@example.com",
        mailbox_folder="Inbox",
        openrouter_api_key="sk-test",
        llm_model="claude-sonnet-4-6-20250514",
        digest_recipient="user@example.com",
    )


def _mock_response(status_code: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    """Build a mock httpx.Response."""
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.text = text
    if json_body is not None:
        mock.json.return_value = json_body
        mock.headers = {"content-type": "application/json"}
    else:
        mock.headers = {}
    return mock


class TestGetGraphTokenErrors:
    def test_raises_permission_error_on_401(self) -> None:
        """A 401 from the token endpoint raises PermissionError."""
        response = _mock_response(
            401,
            json_body={"error": "invalid_client", "error_description": "Bad credentials"},
        )
        with (
            patch("httpx.post", return_value=response),
            pytest.raises(PermissionError, match="Authentication failed"),
        ):
            get_graph_token(_make_config())

    def test_raises_permission_error_on_400(self) -> None:
        """A 400 from the token endpoint raises PermissionError."""
        response = _mock_response(
            400,
            json_body={"error": "invalid_request", "error_description": "Malformed request"},
        )
        with (
            patch("httpx.post", return_value=response),
            pytest.raises(PermissionError, match="Authentication failed"),
        ):
            get_graph_token(_make_config())

    def test_raises_runtime_error_on_500(self) -> None:
        """A 500 from the token endpoint raises RuntimeError."""
        response = _mock_response(500, text="Internal Server Error")
        with (
            patch("httpx.post", return_value=response),
            pytest.raises(RuntimeError, match="Token request failed \\(500\\)"),
        ):
            get_graph_token(_make_config())

    def test_raises_connection_error_on_timeout(self) -> None:
        """A network timeout raises ConnectionError."""
        with (
            patch("httpx.post", side_effect=httpx.TimeoutException("timed out")),
            pytest.raises(ConnectionError, match="Network error acquiring Graph token"),
        ):
            get_graph_token(_make_config())

    def test_permission_error_includes_status_code(self) -> None:
        """PermissionError message includes the HTTP status code."""
        response = _mock_response(401, json_body={"error_description": "Token expired"})
        with (
            patch("httpx.post", return_value=response),
            pytest.raises(PermissionError, match="401"),
        ):
            get_graph_token(_make_config())

    def test_permission_error_falls_back_to_text_when_not_json(self) -> None:
        """When the 401 response is not JSON, the raw text is used in the error message."""
        mock = MagicMock(spec=httpx.Response)
        mock.status_code = 401
        mock.text = "Unauthorized"
        mock.headers = {"content-type": "text/plain"}
        # json() should not be called; if it is, raise to catch the bug
        mock.json.side_effect = AssertionError("json() called on non-JSON response")
        with (
            patch("httpx.post", return_value=mock),
            pytest.raises(PermissionError, match="Unauthorized"),
        ):
            get_graph_token(_make_config())


class TestGetGraphTokenSuccess:
    def test_returns_access_token_string(self) -> None:
        """On success, the access_token value is returned."""
        response = _mock_response(
            200,
            json_body={"access_token": "my-bearer-token", "expires_in": 3600},
        )
        with patch("httpx.post", return_value=response):
            token = get_graph_token(_make_config())
        assert token == "my-bearer-token"

    def test_logs_expiry_time_on_success(self, caplog: pytest.LogCaptureFixture) -> None:
        """On success, the token expiry time is logged at INFO level."""
        response = _mock_response(
            200,
            json_body={"access_token": "tok", "expires_in": 3600},
        )
        with (
            patch("httpx.post", return_value=response),
            caplog.at_level(logging.INFO, logger="email_ingester.auth"),
        ):
            get_graph_token(_make_config())

        assert any("expires at" in record.message for record in caplog.records)

    def test_logs_expiry_unknown_when_expires_in_missing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When expires_in is absent, the log notes that expiry is unknown."""
        response = _mock_response(
            200,
            json_body={"access_token": "tok"},
        )
        with (
            patch("httpx.post", return_value=response),
            caplog.at_level(logging.INFO, logger="email_ingester.auth"),
        ):
            get_graph_token(_make_config())

        assert any("expiry unknown" in record.message for record in caplog.records)

    def test_expiry_log_includes_seconds_remaining(self, caplog: pytest.LogCaptureFixture) -> None:
        """The expiry log message includes the seconds-remaining value (expires_in)."""
        response = _mock_response(
            200,
            json_body={"access_token": "tok", "expires_in": 3600},
        )
        with (
            patch("httpx.post", return_value=response),
            caplog.at_level(logging.INFO, logger="email_ingester.auth"),
        ):
            get_graph_token(_make_config())

        assert any("3600" in record.message for record in caplog.records)
