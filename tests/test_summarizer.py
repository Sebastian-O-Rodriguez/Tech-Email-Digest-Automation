"""Tests for LLM summarizer error handling."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import anthropic
import pytest

from email_ingester.config import Config
from email_ingester.models import Email, EmailSummary
from email_ingester.summarizer import summarize_batch, summarize_email


@pytest.fixture
def config() -> Config:
    return Config(
        azure_tenant_id="tenant",
        azure_client_id="client",
        azure_client_secret="secret",
        mailbox_user_id="user@example.com",
        mailbox_folder="Inbox",
        anthropic_api_key="test-key",
        llm_model="claude-test-model",
        digest_recipient="user@example.com",
        state_file="state.json",
    )


@pytest.fixture
def sample_email() -> Email:
    return Email(
        id="email-001",
        subject="Interesting Article",
        sender="news@example.com",
        timestamp=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
        body_text="A great article about software engineering.",
        body_html="<p>A great article about software engineering.</p>",
        links=["https://example.com/article"],
    )


def _make_mock_message(text: str) -> MagicMock:
    """Build a mock anthropic message with a single text content block."""
    block = MagicMock()
    block.text = text
    message = MagicMock()
    message.content = [block]
    return message


def _valid_llm_json() -> str:
    return json.dumps(
        {
            "summary": "A useful article on engineering.",
            "priority": "medium",
            "why_it_matters": "Relevant to current work.",
            "recommended_action": "Read the article.",
            "key_links": ["https://example.com/article"],
        }
    )


class TestSummarizeEmail:
    def test_successful_summarization_returns_email_summary(
        self, config: Config, sample_email: Email
    ):
        client = MagicMock(spec=anthropic.Anthropic)
        client.messages.create.return_value = _make_mock_message(_valid_llm_json())

        result = summarize_email(config, client, sample_email)

        assert isinstance(result, EmailSummary)
        assert result.email_id == sample_email.id
        assert result.summary == "A useful article on engineering."
        assert result.priority == "medium"
        assert result.why_it_matters == "Relevant to current work."
        assert result.recommended_action == "Read the article."
        assert result.key_links == ["https://example.com/article"]
        assert result.model_confidence == 0.5

    def test_json_parse_error_returns_fallback(self, config: Config, sample_email: Email):
        client = MagicMock(spec=anthropic.Anthropic)
        client.messages.create.return_value = _make_mock_message("not valid json {{")

        result = summarize_email(config, client, sample_email)

        assert isinstance(result, EmailSummary)
        assert result.email_id == sample_email.id
        assert result.summary == "(summarization failed)"
        assert result.priority == "low"
        assert result.model_confidence == 0.0

    def test_api_error_returns_fallback(self, config: Config, sample_email: Email):
        client = MagicMock(spec=anthropic.Anthropic)
        client.messages.create.side_effect = anthropic.APIStatusError(
            message="Internal Server Error",
            response=MagicMock(status_code=500),
            body={},
        )

        result = summarize_email(config, client, sample_email)

        assert isinstance(result, EmailSummary)
        assert result.summary == "(summarization failed)"
        assert result.priority == "low"
        assert result.model_confidence == 0.0

    def test_empty_content_in_response_returns_fallback(self, config: Config, sample_email: Email):
        client = MagicMock(spec=anthropic.Anthropic)
        message = MagicMock()
        message.content = []
        client.messages.create.return_value = message

        result = summarize_email(config, client, sample_email)

        assert result.summary == "(summarization failed)"
        assert result.priority == "low"
        assert result.model_confidence == 0.0

    def test_blank_text_in_content_block_returns_fallback(
        self, config: Config, sample_email: Email
    ):
        client = MagicMock(spec=anthropic.Anthropic)
        client.messages.create.return_value = _make_mock_message("   ")

        result = summarize_email(config, client, sample_email)

        assert result.summary == "(summarization failed)"
        assert result.priority == "low"
        assert result.model_confidence == 0.0


class TestSummarizeBatch:
    def test_continues_after_single_email_failure(self, config: Config):
        email_a = Email(
            id="a",
            subject="Good Email",
            sender="a@example.com",
            timestamp=datetime(2026, 3, 23, tzinfo=UTC),
            body_text="Content A",
            body_html="",
            links=[],
        )
        email_b = Email(
            id="b",
            subject="Failing Email",
            sender="b@example.com",
            timestamp=datetime(2026, 3, 23, tzinfo=UTC),
            body_text="Content B",
            body_html="",
            links=[],
        )

        client = MagicMock(spec=anthropic.Anthropic)

        def side_effect(*, model, max_tokens, system, messages):
            content = messages[0]["content"]
            if "Subject: Good Email" in content:
                return _make_mock_message(_valid_llm_json())
            raise anthropic.APIStatusError(
                message="Service Unavailable",
                response=MagicMock(status_code=503),
                body={},
            )

        client.messages.create.side_effect = side_effect

        results = summarize_batch(config, client, [email_a, email_b])

        assert len(results) == 2

        email_result_a, summary_a = results[0]
        assert email_result_a.id == "a"
        assert summary_a.summary != "(summarization failed)"

        email_result_b, summary_b = results[1]
        assert email_result_b.id == "b"
        assert summary_b.summary == "(summarization failed)"
        assert summary_b.model_confidence == 0.0

    def test_returns_email_summary_pairs(self, config: Config, sample_email: Email):
        client = MagicMock(spec=anthropic.Anthropic)
        client.messages.create.return_value = _make_mock_message(_valid_llm_json())

        results = summarize_batch(config, client, [sample_email])

        assert len(results) == 1
        email, summary = results[0]
        assert email is sample_email
        assert isinstance(summary, EmailSummary)

    def test_empty_batch_returns_empty_list(self, config: Config):
        client = MagicMock(spec=anthropic.Anthropic)
        results = summarize_batch(config, client, [])
        assert results == []
