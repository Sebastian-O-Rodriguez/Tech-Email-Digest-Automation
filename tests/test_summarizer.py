"""Tests for LLM summarizer error handling."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import openai
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
        openrouter_api_key="test-key",
        llm_model="anthropic/claude-sonnet-4",
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


def _make_mock_response(text: str) -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _valid_llm_json() -> str:
    return json.dumps(
        {
            "summary": "A useful article on engineering.",
            "topic": "deep_dives",
            "key_links": ["https://example.com/article"],
        }
    )


class TestSummarizeEmail:
    def test_successful_summarization_returns_email_summary(
        self, config: Config, sample_email: Email
    ):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.return_value = _make_mock_response(_valid_llm_json())

        result = summarize_email(config, client, sample_email)

        assert isinstance(result, EmailSummary)
        assert result.email_id == sample_email.id
        assert result.summary == "A useful article on engineering."
        assert result.topic == "deep_dives"
        assert result.key_links == ["https://example.com/article"]
        assert result.model_confidence == 0.5

    def test_json_parse_error_returns_fallback(self, config: Config, sample_email: Email):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.return_value = _make_mock_response("not valid json {{")

        result = summarize_email(config, client, sample_email)

        assert isinstance(result, EmailSummary)
        assert result.email_id == sample_email.id
        assert result.summary == "(summarization failed)"
        assert result.topic == "deep_dives"
        assert result.model_confidence == 0.0

    def test_api_error_returns_fallback(self, config: Config, sample_email: Email):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.side_effect = openai.APIStatusError(
            message="Internal Server Error",
            response=MagicMock(status_code=500),
            body={},
        )

        result = summarize_email(config, client, sample_email)

        assert isinstance(result, EmailSummary)
        assert result.summary == "(summarization failed)"
        assert result.topic == "deep_dives"
        assert result.model_confidence == 0.0

    def test_empty_choices_in_response_returns_fallback(self, config: Config, sample_email: Email):
        client = MagicMock(spec=openai.OpenAI)
        response = MagicMock()
        response.choices = []
        client.chat.completions.create.return_value = response

        result = summarize_email(config, client, sample_email)

        assert result.summary == "(summarization failed)"
        assert result.topic == "deep_dives"
        assert result.model_confidence == 0.0

    def test_blank_text_in_response_returns_fallback(self, config: Config, sample_email: Email):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.return_value = _make_mock_response("   ")

        result = summarize_email(config, client, sample_email)

        assert result.summary == "(summarization failed)"
        assert result.topic == "deep_dives"
        assert result.model_confidence == 0.0

    def test_unknown_topic_defaults_to_deep_dives(self, config: Config, sample_email: Email):
        client = MagicMock(spec=openai.OpenAI)
        bad_topic_json = json.dumps({"summary": "Test", "topic": "garbage", "key_links": []})
        client.chat.completions.create.return_value = _make_mock_response(bad_topic_json)

        result = summarize_email(config, client, sample_email)
        assert result.topic == "deep_dives"

    def test_summary_truncated_to_75_chars(self, config: Config, sample_email: Email):
        client = MagicMock(spec=openai.OpenAI)
        long_summary = "A" * 100
        long_json = json.dumps({"summary": long_summary, "topic": "breaking_news", "key_links": []})
        client.chat.completions.create.return_value = _make_mock_response(long_json)

        result = summarize_email(config, client, sample_email)
        assert len(result.summary) <= 75


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

        client = MagicMock(spec=openai.OpenAI)

        def side_effect(*, model, max_tokens, messages):
            user_msg = messages[1]["content"]
            if "Subject: Good Email" in user_msg:
                return _make_mock_response(_valid_llm_json())
            raise openai.APIStatusError(
                message="Service Unavailable",
                response=MagicMock(status_code=503),
                body={},
            )

        client.chat.completions.create.side_effect = side_effect

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
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.return_value = _make_mock_response(_valid_llm_json())

        results = summarize_batch(config, client, [sample_email])

        assert len(results) == 1
        email, summary = results[0]
        assert email is sample_email
        assert isinstance(summary, EmailSummary)

    def test_empty_batch_returns_empty_list(self, config: Config):
        client = MagicMock(spec=openai.OpenAI)
        results = summarize_batch(config, client, [])
        assert results == []
