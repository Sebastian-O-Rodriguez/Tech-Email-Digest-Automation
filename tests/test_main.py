"""Tests for the main() pipeline entry point in main.py."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

from email_ingester.config import Config

if TYPE_CHECKING:
    from pathlib import Path
from email_ingester.models import DigestOutput, DigestReport, Email, State


def _make_config() -> Config:
    return Config(
        azure_tenant_id="tenant-id",
        azure_client_id="client-id",
        azure_client_secret="client-secret",
        mailbox_user_id="user@example.com",
        mailbox_folder="Inbox",
        openrouter_api_key="sk-test",
        llm_model="anthropic/claude-sonnet-4",
        digest_recipient="recipient@example.com",
        state_file="state.json",
    )


def _make_raw_email() -> Email:
    return Email(
        id="msg-001",
        subject="Test Subject",
        sender="sender@example.com",
        timestamp=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
        body_text="Body text.",
        body_html="<p>Body text.</p>",
        links=["https://example.com"],
    )


def _make_report() -> DigestReport:
    return DigestReport(
        breaking_news="Test breaking news.",
        tech_stacks="Test stacks.",
        new_software="Test software.",
        deep_dives="Test dives.",
    )


def _make_digest() -> DigestOutput:
    return DigestOutput(
        generated_at=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
        total_processed=1,
        report=_make_report(),
        html="<html><body>Digest</body></html>",
    )


_PATCHES = {
    "config": "email_ingester.main.Config.from_env",
    "token": "email_ingester.main.get_graph_token",
    "load_state": "email_ingester.main.load_state",
    "fetch": "email_ingester.main.fetch_new_emails",
    "process": "email_ingester.main.process_email",
    "report": "email_ingester.main.generate_report",
    "digest": "email_ingester.main.generate_digest",
    "send": "email_ingester.main.send_digest",
    "fetch_unread": "email_ingester.main.fetch_unread_emails",
    "mark_read": "email_ingester.main.mark_as_read",
    "save_state": "email_ingester.main.save_state",
    "create_client": "email_ingester.main.create_client",
}


class TestMainHappyPath:
    def test_happy_path_saves_state(self, tmp_path: Path):
        config = _make_config()
        initial_state = State()
        new_state = State(processed_ids={"msg-001"})
        raw_email = _make_raw_email()
        digest = _make_digest()

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([raw_email], new_state)),
            patch(_PATCHES["process"], return_value=raw_email),
            patch(_PATCHES["report"], return_value=_make_report()),
            patch(_PATCHES["digest"], return_value=digest),
            patch(_PATCHES["send"]) as mock_send,
            patch(_PATCHES["mark_read"]),
            patch(_PATCHES["save_state"]) as mock_save,
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        mock_send.assert_called_once()
        mock_save.assert_called_once()

    def test_happy_path_sends_digest(self, tmp_path: Path):
        config = _make_config()
        initial_state = State()
        new_state = State(processed_ids={"msg-001"})
        raw_email = _make_raw_email()
        digest = _make_digest()

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([raw_email], new_state)),
            patch(_PATCHES["process"], return_value=raw_email),
            patch(_PATCHES["report"], return_value=_make_report()),
            patch(_PATCHES["digest"], return_value=digest),
            patch(_PATCHES["send"]) as mock_send,
            patch(_PATCHES["mark_read"]),
            patch(_PATCHES["save_state"]),
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        call_args = mock_send.call_args
        assert call_args[0][2] is digest

    def test_happy_path_marks_emails_as_read(self, tmp_path: Path):
        config = _make_config()
        initial_state = State()
        new_state = State(processed_ids={"msg-001"})
        raw_email = _make_raw_email()
        digest = _make_digest()

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([raw_email], new_state)),
            patch(_PATCHES["process"], return_value=raw_email),
            patch(_PATCHES["report"], return_value=_make_report()),
            patch(_PATCHES["digest"], return_value=digest),
            patch(_PATCHES["send"]),
            patch(_PATCHES["mark_read"]) as mock_mark,
            patch(_PATCHES["save_state"]),
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        mock_mark.assert_called_once()


class TestMainNoNewEmails:
    def test_no_emails_skips_digest_and_saves_state(self):
        config = _make_config()
        initial_state = State()
        new_state = State(delta_token="new-token")

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([], new_state)),
            patch(_PATCHES["fetch_unread"], return_value=([], new_state)),
            patch(_PATCHES["process"]) as mock_process,
            patch(_PATCHES["report"]) as mock_report,
            patch(_PATCHES["digest"]) as mock_digest,
            patch(_PATCHES["send"]) as mock_send,
            patch(_PATCHES["mark_read"]) as mock_mark,
            patch(_PATCHES["save_state"]) as mock_save,
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        mock_process.assert_not_called()
        mock_report.assert_not_called()
        mock_digest.assert_not_called()
        mock_send.assert_not_called()
        mock_mark.assert_not_called()
        mock_save.assert_called_once()

    def test_no_emails_saves_updated_state(self):
        config = _make_config()
        initial_state = State(delta_token="old-token")
        new_state = State(delta_token="new-token")

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([], new_state)),
            patch(_PATCHES["fetch_unread"], return_value=([], new_state)),
            patch(_PATCHES["send"]),
            patch(_PATCHES["mark_read"]),
            patch(_PATCHES["save_state"]) as mock_save,
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        saved_state = mock_save.call_args[0][1]
        assert saved_state is new_state


class TestMainSendFailure:
    def test_send_failure_does_not_prevent_state_save(self):
        config = _make_config()
        initial_state = State()
        new_state = State(processed_ids={"msg-001"})
        raw_email = _make_raw_email()
        digest = _make_digest()

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([raw_email], new_state)),
            patch(_PATCHES["process"], return_value=raw_email),
            patch(_PATCHES["report"], return_value=_make_report()),
            patch(_PATCHES["digest"], return_value=digest),
            patch(_PATCHES["send"], side_effect=Exception("send failed")),
            patch(_PATCHES["mark_read"]),
            patch(_PATCHES["save_state"]) as mock_save,
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        mock_save.assert_called_once()

    def test_send_failure_saves_correct_state(self):
        config = _make_config()
        initial_state = State()
        new_state = State(processed_ids={"msg-001"}, delta_token="updated-token")
        raw_email = _make_raw_email()
        digest = _make_digest()

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([raw_email], new_state)),
            patch(_PATCHES["process"], return_value=raw_email),
            patch(_PATCHES["report"], return_value=_make_report()),
            patch(_PATCHES["digest"], return_value=digest),
            patch(_PATCHES["send"], side_effect=Exception("network down")),
            patch(_PATCHES["mark_read"]),
            patch(_PATCHES["save_state"]) as mock_save,
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        saved_state = mock_save.call_args[0][1]
        assert saved_state is new_state
