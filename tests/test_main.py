"""Tests for the main() pipeline entry point."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from email_ingester.config import Config
from email_ingester.models import DigestOutput, DigestReport, Email


def _make_config() -> Config:
    return Config(
        azure_tenant_id="tenant-id",
        azure_client_id="client-id",
        azure_client_secret="client-secret",
        mailbox_user_id="user@example.com",
        mailbox_folder="Inbox",
        openrouter_api_key="sk-test",
        llm_model="test-model",
        digest_recipient="recipient@example.com",
    )


def _make_email() -> Email:
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
        strategic_intel="Test breaking news.",
        engineering="Test stacks.",
        tools_and_ops="Test software.",
        radar="Test dives.",
    )


def _make_digest() -> DigestOutput:
    return DigestOutput(
        generated_at=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
        total_processed=1,
        report=_make_report(),
        html="<html><body>Digest</body></html>",
    )


_P = {
    "config": "email_ingester.main.Config.from_env",
    "token": "email_ingester.main.get_graph_token",
    "fetch": "email_ingester.main.fetch_unread_emails",
    "process": "email_ingester.main.process_email",
    "report": "email_ingester.main.generate_report",
    "digest": "email_ingester.main.generate_digest",
    "send": "email_ingester.main.send_digest",
    "mark_read": "email_ingester.main.mark_as_read",
    "create_client": "email_ingester.main.create_client",
}


class TestMainHappyPath:
    def test_sends_digest_and_marks_read(self):
        config = _make_config()
        email = _make_email()
        digest = _make_digest()

        with (
            patch(_P["config"], return_value=config),
            patch(_P["token"], return_value="token"),
            patch(_P["fetch"], return_value=[email]),
            patch(_P["process"], return_value=email),
            patch(_P["report"], return_value=_make_report()),
            patch(_P["digest"], return_value=digest),
            patch(_P["send"]) as mock_send,
            patch(_P["mark_read"]) as mock_mark,
            patch(_P["create_client"]),
        ):
            from email_ingester.main import main

            main()

        mock_send.assert_called_once()
        mock_mark.assert_called_once()


class TestMainNoEmails:
    def test_no_unread_skips_everything(self):
        config = _make_config()

        with (
            patch(_P["config"], return_value=config),
            patch(_P["token"], return_value="token"),
            patch(_P["fetch"], return_value=[]),
            patch(_P["process"]) as mock_process,
            patch(_P["report"]) as mock_report,
            patch(_P["send"]) as mock_send,
            patch(_P["mark_read"]) as mock_mark,
            patch(_P["create_client"]),
        ):
            from email_ingester.main import main

            main()

        mock_process.assert_not_called()
        mock_report.assert_not_called()
        mock_send.assert_not_called()
        mock_mark.assert_not_called()


class TestMainSendFailure:
    def test_send_failure_still_marks_read(self):
        config = _make_config()
        email = _make_email()
        digest = _make_digest()

        with (
            patch(_P["config"], return_value=config),
            patch(_P["token"], return_value="token"),
            patch(_P["fetch"], return_value=[email]),
            patch(_P["process"], return_value=email),
            patch(_P["report"], return_value=_make_report()),
            patch(_P["digest"], return_value=digest),
            patch(_P["send"], side_effect=Exception("send failed")),
            patch(_P["mark_read"]) as mock_mark,
            patch(_P["create_client"]),
        ):
            from email_ingester.main import main

            main()

        mock_mark.assert_called_once()
