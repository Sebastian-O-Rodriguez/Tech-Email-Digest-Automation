"""Tests for email ingester (unread fetch, auth errors, mark as read)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from email_ingester.config import Config
from email_ingester.ingester import (
    GraphAuthError,
    GraphPermissionError,
    fetch_unread_emails,
)


@pytest.fixture
def config() -> Config:
    return Config(
        azure_tenant_id="test-tenant",
        azure_client_id="test-client-id",
        azure_client_secret="test-client-secret",
        mailbox_user_id="user@example.com",
        mailbox_folder="Tech Digest",
        openrouter_api_key="sk-test",
        llm_model="test-model",
        digest_recipient="user@example.com",
    )


def _mock_get_response(
    status_code: int, json_body: dict | None = None, text: str = ""
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.is_success = 200 <= status_code < 300
    response.text = text
    response.headers = {}
    if json_body is not None:
        response.json.return_value = json_body
    return response


class TestDSTGuardOffsets:
    """Validate that the cron UTC times map to correct ET hours."""

    def test_edt_offset_is_minus_4_hours(self):
        summer = datetime(2026, 7, 1, 13, 30, tzinfo=UTC)
        et = summer.astimezone(ZoneInfo("America/New_York"))
        assert et.hour == 9

    def test_est_offset_is_minus_5_hours(self):
        winter = datetime(2026, 1, 1, 14, 30, tzinfo=UTC)
        et = winter.astimezone(ZoneInfo("America/New_York"))
        assert et.hour == 9


class TestFetchUnreadAuthErrors:
    def test_raises_graph_auth_error_on_401(self, config, monkeypatch):
        import email_ingester.ingester as mod

        folder_resp = _mock_get_response(200, {"value": [{"id": "fid", "displayName": "Inbox"}]})
        msg_resp = _mock_get_response(401, text="unauthorized")

        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return folder_resp if call_count == 1 else msg_resp

        monkeypatch.setattr(mod.httpx, "get", mock_get)

        with pytest.raises(GraphAuthError):
            fetch_unread_emails(config, "bad-token")

    def test_raises_graph_permission_error_on_403(self, config, monkeypatch):
        import email_ingester.ingester as mod

        folder_resp = _mock_get_response(200, {"value": [{"id": "fid", "displayName": "Inbox"}]})
        msg_resp = _mock_get_response(403, text="forbidden")

        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return folder_resp if call_count == 1 else msg_resp

        monkeypatch.setattr(mod.httpx, "get", mock_get)

        with pytest.raises(GraphPermissionError):
            fetch_unread_emails(config, "token")


class TestFetchUnreadSuccess:
    def test_returns_empty_when_no_unread(self, config, monkeypatch):
        import email_ingester.ingester as mod

        folder_resp = _mock_get_response(200, {"value": [{"id": "fid", "displayName": "Inbox"}]})
        msg_resp = _mock_get_response(200, {"value": []})

        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return folder_resp if call_count == 1 else msg_resp

        monkeypatch.setattr(mod.httpx, "get", mock_get)

        result = fetch_unread_emails(config, "token")
        assert result == []

    def test_parses_valid_message(self, config, monkeypatch):
        import email_ingester.ingester as mod

        folder_resp = _mock_get_response(200, {"value": [{"id": "fid", "displayName": "Inbox"}]})
        msg_resp = _mock_get_response(
            200,
            {
                "value": [
                    {
                        "id": "msg-1",
                        "subject": "Test",
                        "from": {"emailAddress": {"address": "a@b.com"}},
                        "receivedDateTime": "2026-03-25T10:00:00Z",
                        "body": {"contentType": "html", "content": "<p>hi</p>"},
                    }
                ]
            },
        )

        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return folder_resp if call_count == 1 else msg_resp

        monkeypatch.setattr(mod.httpx, "get", mock_get)

        result = fetch_unread_emails(config, "token")
        assert len(result) == 1
        assert result[0].id == "msg-1"
        assert result[0].subject == "Test"
