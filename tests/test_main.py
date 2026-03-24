"""Tests for the main() pipeline entry point in main.py."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

from email_ingester.config import Config

if TYPE_CHECKING:
    from pathlib import Path
from email_ingester.models import DigestOutput, Email, ProcessedEmail, State


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


def _make_processed_email() -> ProcessedEmail:
    return ProcessedEmail(
        email=_make_raw_email(),
        summary="A test email summary.",
        topic="breaking_news",
        key_links=["https://example.com"],
        score=0.8,
    )


def _make_digest() -> DigestOutput:
    processed = _make_processed_email()
    return DigestOutput(
        generated_at=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
        total_processed=1,
        breaking_news=[processed],
        html="<html><body>Digest</body></html>",
    )


# Patch targets — all resolved relative to email_ingester.main where they are imported
_PATCHES = {
    "config": "email_ingester.main.Config.from_env",
    "token": "email_ingester.main.get_graph_token",
    "load_state": "email_ingester.main.load_state",
    "fetch": "email_ingester.main.fetch_new_emails",
    "process": "email_ingester.main.process_email",
    "summarize": "email_ingester.main.summarize_batch",
    "score": "email_ingester.main.score_and_rank",
    "generate": "email_ingester.main.generate_digest",
    "send": "email_ingester.main.send_digest",
    "save_state": "email_ingester.main.save_state",
    "create_client": "email_ingester.main.create_client",
}


class TestMainHappyPath:
    def test_happy_path_saves_state(self, tmp_path: Path):
        """All steps succeed — state is saved at the end."""
        config = _make_config()
        initial_state = State()
        new_state = State(processed_ids={"msg-001"})
        raw_email = _make_raw_email()
        processed = _make_processed_email()
        digest = _make_digest()

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([raw_email], new_state)),
            patch(_PATCHES["process"], return_value=processed),
            patch(_PATCHES["summarize"], return_value=[processed]),
            patch(_PATCHES["score"], return_value=[processed]),
            patch(_PATCHES["generate"], return_value=digest),
            patch(_PATCHES["send"]) as mock_send,
            patch(_PATCHES["save_state"]) as mock_save,
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        mock_send.assert_called_once()
        mock_save.assert_called_once()

    def test_happy_path_sends_digest(self, tmp_path: Path):
        """All steps succeed — send_digest is called with the generated digest."""
        config = _make_config()
        initial_state = State()
        new_state = State(processed_ids={"msg-001"})
        raw_email = _make_raw_email()
        processed = _make_processed_email()
        digest = _make_digest()

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([raw_email], new_state)),
            patch(_PATCHES["process"], return_value=processed),
            patch(_PATCHES["summarize"], return_value=[processed]),
            patch(_PATCHES["score"], return_value=[processed]),
            patch(_PATCHES["generate"], return_value=digest),
            patch(_PATCHES["send"]) as mock_send,
            patch(_PATCHES["save_state"]),
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        call_args = mock_send.call_args
        assert call_args[0][2] is digest


class TestMainNoNewEmails:
    def test_no_emails_skips_digest_and_saves_state(self):
        """When fetch returns empty list, digest steps are skipped and state is still saved."""
        config = _make_config()
        initial_state = State()
        new_state = State(delta_token="new-token")

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([], new_state)),
            patch(_PATCHES["process"]) as mock_process,
            patch(_PATCHES["summarize"]) as mock_summarize,
            patch(_PATCHES["score"]) as mock_score,
            patch(_PATCHES["generate"]) as mock_generate,
            patch(_PATCHES["send"]) as mock_send,
            patch(_PATCHES["save_state"]) as mock_save,
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        mock_process.assert_not_called()
        mock_summarize.assert_not_called()
        mock_score.assert_not_called()
        mock_generate.assert_not_called()
        mock_send.assert_not_called()
        mock_save.assert_called_once()

    def test_no_emails_saves_updated_state(self):
        """When there are no new emails, the new state (not old state) is saved."""
        config = _make_config()
        initial_state = State(delta_token="old-token")
        new_state = State(delta_token="new-token")

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([], new_state)),
            patch(_PATCHES["send"]),
            patch(_PATCHES["save_state"]) as mock_save,
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        saved_state = mock_save.call_args[0][1]
        assert saved_state is new_state


class TestMainSendFailure:
    def test_send_failure_does_not_prevent_state_save(self):
        """When send_digest raises, save_state is still called — the key invariant."""
        config = _make_config()
        initial_state = State()
        new_state = State(processed_ids={"msg-001"})
        raw_email = _make_raw_email()
        processed = _make_processed_email()
        digest = _make_digest()

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([raw_email], new_state)),
            patch(_PATCHES["process"], return_value=processed),
            patch(_PATCHES["summarize"], return_value=[processed]),
            patch(_PATCHES["score"], return_value=[processed]),
            patch(_PATCHES["generate"], return_value=digest),
            patch(_PATCHES["send"], side_effect=Exception("send failed")),
            patch(_PATCHES["save_state"]) as mock_save,
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            # main() should not raise even when send_digest raises
            main()

        mock_save.assert_called_once()

    def test_send_failure_saves_correct_state(self):
        """After send failure, the new state (with updated IDs) is what gets saved."""
        config = _make_config()
        initial_state = State()
        new_state = State(processed_ids={"msg-001"}, delta_token="updated-token")
        raw_email = _make_raw_email()
        processed = _make_processed_email()
        digest = _make_digest()

        with (
            patch(_PATCHES["config"], return_value=config),
            patch(_PATCHES["token"], return_value="bearer-token"),
            patch(_PATCHES["load_state"], return_value=initial_state),
            patch(_PATCHES["fetch"], return_value=([raw_email], new_state)),
            patch(_PATCHES["process"], return_value=processed),
            patch(_PATCHES["summarize"], return_value=[processed]),
            patch(_PATCHES["score"], return_value=[processed]),
            patch(_PATCHES["generate"], return_value=digest),
            patch(_PATCHES["send"], side_effect=Exception("network down")),
            patch(_PATCHES["save_state"]) as mock_save,
            patch(_PATCHES["create_client"]),
        ):
            from email_ingester.main import main

            main()

        saved_state = mock_save.call_args[0][1]
        assert saved_state is new_state
