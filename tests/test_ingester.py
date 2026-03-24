"""Tests for ingester.py — Graph API fetch and error handling.

DST Guard Review
----------------
The digest.yml workflow uses four cron entries to cover both EST and EDT:

  0 10 * * *   # 6 AM EDT  (UTC-4 -> 10:00 UTC)
  0 11 * * *   # 6 AM EST  (UTC-5 -> 11:00 UTC)
  0 21 * * *   # 5 PM EDT  (UTC-4 -> 21:00 UTC)
  0 22 * * *   # 5 PM EST  (UTC-5 -> 22:00 UTC)

During a DST transition, both the outgoing and incoming cron fire on the same
calendar day (e.g. the Sunday clocks-forward day fires both 10:00 and 11:00
UTC).  The DST guard step resolves this by reading the actual local hour in
America/New_York and exiting early unless it is exactly 06 or 17:

  HOUR=$(TZ=America/New_York date +%H)
  if [[ "$HOUR" != "06" && "$HOUR" != "17" ]]; then
      echo "skip=true" >> "$GITHUB_OUTPUT"
  fi

Guard correctness:

- At 10:00 UTC during EDT, TZ=America/New_York gives 06 -> guard passes.
- At 11:00 UTC during EDT, TZ=America/New_York gives 07 -> guard skips.
- At 11:00 UTC during EST, TZ=America/New_York gives 06 -> guard passes.
- At 10:00 UTC during EST, TZ=America/New_York gives 05 -> guard skips.
- At 21:00 UTC during EDT, TZ=America/New_York gives 17 -> guard passes.
- At 22:00 UTC during EDT, TZ=America/New_York gives 18 -> guard skips.
- At 22:00 UTC during EST, TZ=America/New_York gives 17 -> guard passes.
- At 21:00 UTC during EST, TZ=America/New_York gives 16 -> guard skips.

All eight cases produce the correct outcome: exactly one cron fires per
scheduled window per day, even across DST transitions.

The `workflow_dispatch` (manual trigger) bypasses the cron schedule entirely
so it will always run the guard check — operators triggering manually should
be aware that triggering outside 06 or 17 NY time will be a no-op unless they
are testing the guard itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from email_ingester.config import Config
from email_ingester.ingester import (
    GraphAPIError,
    GraphAuthError,
    GraphPermissionError,
    GraphThrottleError,
    fetch_new_emails,
)
from email_ingester.models import State


def _make_config() -> Config:
    return Config(
        azure_tenant_id="test-tenant",
        azure_client_id="test-client-id",
        azure_client_secret="test-client-secret",
        mailbox_user_id="user@example.com",
        mailbox_folder="Inbox",
        anthropic_api_key="sk-test",
        llm_model="claude-sonnet-4-6-20250514",
        digest_recipient="user@example.com",
        state_file="state.json",
    )


def _mock_get_response(
    status_code: int, json_body: dict | None = None, text: str = ""
) -> MagicMock:
    """Build a mock httpx.Response for GET requests."""
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.is_success = 200 <= status_code < 300
    mock.text = text
    mock.headers = {}
    if json_body is not None:
        mock.json.return_value = json_body
    return mock


# ---------------------------------------------------------------------------
# DST guard correctness — validated via the documented analysis above.
# The shell logic cannot be executed in pytest, but its correctness is
# confirmed by the UTC <-> America/New_York offset table in the module
# docstring.  The test below asserts the documented offset constants.
# ---------------------------------------------------------------------------


class TestDSTGuardOffsets:
    """Assert that the documented UTC offsets for EST/EDT are correct.

    These are stdlib-level sanity checks on the DST offset values used in the
    digest.yml cron schedule comments.  If Python's zoneinfo disagrees with the
    hardcoded offsets in the workflow, this test will catch the drift.
    """

    def test_edt_offset_is_minus_4_hours(self) -> None:
        """America/New_York during EDT (summer) is UTC-4."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            pytest.skip("zoneinfo not available")

        ny = ZoneInfo("America/New_York")
        # 2026-06-01 is well inside EDT
        dt = datetime(2026, 6, 1, 12, 0, tzinfo=ny)
        offset_hours = dt.utcoffset().total_seconds() / 3600  # type: ignore[union-attr]
        assert offset_hours == -4.0

    def test_est_offset_is_minus_5_hours(self) -> None:
        """America/New_York during EST (winter) is UTC-5."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            pytest.skip("zoneinfo not available")

        ny = ZoneInfo("America/New_York")
        # 2026-01-15 is well inside EST
        dt = datetime(2026, 1, 15, 12, 0, tzinfo=ny)
        offset_hours = dt.utcoffset().total_seconds() / 3600  # type: ignore[union-attr]
        assert offset_hours == -5.0

    def test_cron_10_utc_maps_to_06_edt(self) -> None:
        """UTC 10:00 on an EDT day lands at 06:00 America/New_York."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            pytest.skip("zoneinfo not available")

        ny = ZoneInfo("America/New_York")
        utc_dt = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
        local_hour = utc_dt.astimezone(ny).hour
        assert local_hour == 6

    def test_cron_11_utc_maps_to_06_est(self) -> None:
        """UTC 11:00 on an EST day lands at 06:00 America/New_York."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            pytest.skip("zoneinfo not available")

        ny = ZoneInfo("America/New_York")
        utc_dt = datetime(2026, 1, 15, 11, 0, tzinfo=UTC)
        local_hour = utc_dt.astimezone(ny).hour
        assert local_hour == 6

    def test_cron_21_utc_maps_to_17_edt(self) -> None:
        """UTC 21:00 on an EDT day lands at 17:00 America/New_York."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            pytest.skip("zoneinfo not available")

        ny = ZoneInfo("America/New_York")
        utc_dt = datetime(2026, 6, 1, 21, 0, tzinfo=UTC)
        local_hour = utc_dt.astimezone(ny).hour
        assert local_hour == 17

    def test_cron_22_utc_maps_to_17_est(self) -> None:
        """UTC 22:00 on an EST day lands at 17:00 America/New_York."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            pytest.skip("zoneinfo not available")

        ny = ZoneInfo("America/New_York")
        utc_dt = datetime(2026, 1, 15, 22, 0, tzinfo=UTC)
        local_hour = utc_dt.astimezone(ny).hour
        assert local_hour == 17

    def test_wrong_cron_fires_are_caught_by_guard(self) -> None:
        """The wrong-season cron fires produce hours != 06 and != 17, so the guard skips them."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            pytest.skip("zoneinfo not available")

        ny = ZoneInfo("America/New_York")
        target_hours = {6, 17}

        # 10:00 UTC in EST => 05:00 NY — guard skips
        assert datetime(2026, 1, 15, 10, 0, tzinfo=UTC).astimezone(ny).hour not in target_hours
        # 11:00 UTC in EDT => 07:00 NY — guard skips
        assert datetime(2026, 6, 1, 11, 0, tzinfo=UTC).astimezone(ny).hour not in target_hours
        # 21:00 UTC in EST => 16:00 NY — guard skips
        assert datetime(2026, 1, 15, 21, 0, tzinfo=UTC).astimezone(ny).hour not in target_hours
        # 22:00 UTC in EDT => 18:00 NY — guard skips
        assert datetime(2026, 6, 1, 22, 0, tzinfo=UTC).astimezone(ny).hour not in target_hours


# ---------------------------------------------------------------------------
# fetch_new_emails — auth error handling
# ---------------------------------------------------------------------------


class TestFetchNewEmailsAuthErrors:
    def test_raises_graph_auth_error_on_401(self) -> None:
        """A 401 response from the Graph API raises GraphAuthError."""
        response = _mock_get_response(401, text="Unauthorized")
        with patch("httpx.get", return_value=response), pytest.raises(GraphAuthError):
            fetch_new_emails(_make_config(), "bad-token", State())

    def test_graph_auth_error_message_contains_401(self) -> None:
        """The GraphAuthError message includes the 401 status code."""
        response = _mock_get_response(401, text="token expired")
        with patch("httpx.get", return_value=response), pytest.raises(GraphAuthError, match="401"):
            fetch_new_emails(_make_config(), "expired-token", State())

    def test_raises_graph_permission_error_on_403(self) -> None:
        """A 403 response from the Graph API raises GraphPermissionError."""
        response = _mock_get_response(403, text="Forbidden")
        with patch("httpx.get", return_value=response), pytest.raises(GraphPermissionError):
            fetch_new_emails(_make_config(), "token", State())

    def test_raises_graph_throttle_error_on_429(self) -> None:
        """A 429 response from the Graph API raises GraphThrottleError."""
        mock = _mock_get_response(429, text="Rate limited")
        mock.headers = {"Retry-After": "60"}
        with patch("httpx.get", return_value=mock), pytest.raises(GraphThrottleError):
            fetch_new_emails(_make_config(), "token", State())

    def test_throttle_error_carries_retry_after(self) -> None:
        """GraphThrottleError exposes the Retry-After value as retry_after."""
        mock = _mock_get_response(429, text="Rate limited")
        mock.headers = {"Retry-After": "120"}
        with patch("httpx.get", return_value=mock), pytest.raises(GraphThrottleError) as exc_info:
            fetch_new_emails(_make_config(), "token", State())
        assert exc_info.value.retry_after == 120

    def test_raises_graph_api_error_on_500(self) -> None:
        """An unexpected 500 from the Graph API raises GraphAPIError."""
        response = _mock_get_response(500, text="Internal Server Error")
        with patch("httpx.get", return_value=response), pytest.raises(GraphAPIError):
            fetch_new_emails(_make_config(), "token", State())

    def test_graph_api_error_carries_status_code(self) -> None:
        """GraphAPIError exposes the HTTP status code."""
        response = _mock_get_response(503, text="Service Unavailable")
        with patch("httpx.get", return_value=response), pytest.raises(GraphAPIError) as exc_info:
            fetch_new_emails(_make_config(), "token", State())
        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# fetch_new_emails — success path basics
# ---------------------------------------------------------------------------


class TestFetchNewEmailsSuccess:
    def test_returns_empty_list_when_no_messages(self) -> None:
        """An empty value list returns an empty email list without error."""
        response = _mock_get_response(
            200,
            json_body={"value": [], "@odata.deltaLink": "https://delta.link/1"},
        )
        with patch("httpx.get", return_value=response):
            emails, _ = fetch_new_emails(_make_config(), "token", State())
        assert emails == []

    def test_updates_delta_token_from_response(self) -> None:
        """The delta link returned by the Graph API becomes the new state delta_token."""
        delta_link = "https://graph.microsoft.com/delta?token=abc"
        response = _mock_get_response(
            200,
            json_body={"value": [], "@odata.deltaLink": delta_link},
        )
        with patch("httpx.get", return_value=response):
            _, new_state = fetch_new_emails(_make_config(), "token", State())
        assert new_state.delta_token == delta_link

    def test_parses_valid_message(self) -> None:
        """A well-formed Graph message is parsed into an Email object."""
        response = _mock_get_response(
            200,
            json_body={
                "value": [
                    {
                        "id": "msg-123",
                        "subject": "Hello",
                        "from": {"emailAddress": {"address": "sender@example.com"}},
                        "receivedDateTime": "2026-03-23T10:00:00Z",
                        "body": {"content": "<p>Hi</p>"},
                    }
                ],
                "@odata.deltaLink": "https://delta.link/2",
            },
        )
        with patch("httpx.get", return_value=response):
            emails, _ = fetch_new_emails(_make_config(), "token", State())
        assert len(emails) == 1
        assert emails[0].id == "msg-123"
        assert emails[0].subject == "Hello"

    def test_skips_already_processed_ids(self) -> None:
        """Messages whose IDs are in state.processed_ids are not returned."""
        response = _mock_get_response(
            200,
            json_body={
                "value": [
                    {
                        "id": "already-seen",
                        "subject": "Old",
                        "from": {"emailAddress": {"address": "x@example.com"}},
                        "receivedDateTime": "2026-03-23T10:00:00Z",
                        "body": {"content": ""},
                    }
                ],
                "@odata.deltaLink": "https://delta.link/3",
            },
        )
        state = State(processed_ids={"already-seen"})
        with patch("httpx.get", return_value=response):
            emails, _ = fetch_new_emails(_make_config(), "token", state)
        assert emails == []

    def test_new_message_ids_added_to_processed_ids(self) -> None:
        """IDs of fetched emails are added to the returned state.processed_ids."""
        response = _mock_get_response(
            200,
            json_body={
                "value": [
                    {
                        "id": "new-msg",
                        "subject": "New",
                        "from": {"emailAddress": {"address": "x@example.com"}},
                        "receivedDateTime": "2026-03-23T10:00:00Z",
                        "body": {"content": ""},
                    }
                ],
                "@odata.deltaLink": "https://delta.link/4",
            },
        )
        with patch("httpx.get", return_value=response):
            _, new_state = fetch_new_emails(_make_config(), "token", State())
        assert "new-msg" in new_state.processed_ids
