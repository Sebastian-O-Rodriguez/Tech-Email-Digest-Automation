"""Tests for aggregated report generation."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import openai
import pytest

from email_ingester.config import Config
from email_ingester.models import DigestReport, Email
from email_ingester.summarizer import generate_report


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
def sample_emails() -> list[Email]:
    return [
        Email(
            id="email-001",
            subject="Breaking: Major outage",
            sender="alerts@example.com",
            timestamp=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
            body_text="A major outage hit AWS us-east-1.",
            body_html="",
            links=["https://example.com/outage"],
        ),
        Email(
            id="email-002",
            subject="New React 20 features",
            sender="news@example.com",
            timestamp=datetime(2026, 3, 23, 11, 0, tzinfo=UTC),
            body_text="React 20 ships with server components by default.",
            body_html="",
            links=["https://example.com/react20"],
        ),
    ]


def _make_mock_response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _valid_report_json() -> str:
    return json.dumps(
        {
            "breaking_news": "AWS us-east-1 experienced a major outage.",
            "tech_stacks": "React 20 ships server components by default.",
            "new_software": "No notable releases this cycle.",
            "deep_dives": "No deep dives worth flagging.",
            "footnotes": [
                {"title": "AWS outage details", "url": "https://example.com/outage"},
                {"title": "React 20 announcement", "url": "https://example.com/react20"},
            ],
        }
    )


class TestGenerateReport:
    def test_successful_report(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.return_value = _make_mock_response(_valid_report_json())

        result = generate_report(config, client, sample_emails)

        assert isinstance(result, DigestReport)
        assert "outage" in result.breaking_news.lower()
        assert "react" in result.tech_stacks.lower()
        assert len(result.footnotes) == 2
        assert result.footnotes[0].title == "AWS outage details"
        assert result.footnotes[0].url == "https://example.com/outage"

    def test_api_error_returns_fallback(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.side_effect = openai.APIStatusError(
            message="Internal Server Error",
            response=MagicMock(status_code=500),
            body={},
        )

        result = generate_report(config, client, sample_emails)

        assert isinstance(result, DigestReport)
        assert "failed" in result.breaking_news.lower()

    def test_json_parse_error_returns_fallback(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.return_value = _make_mock_response("not json {{")

        result = generate_report(config, client, sample_emails)
        assert "failed" in result.breaking_news.lower()

    def test_empty_choices_returns_fallback(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        response = MagicMock()
        response.choices = []
        client.chat.completions.create.return_value = response

        result = generate_report(config, client, sample_emails)
        assert "failed" in result.breaking_news.lower()

    def test_blank_response_returns_fallback(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.return_value = _make_mock_response("   ")

        result = generate_report(config, client, sample_emails)
        assert "failed" in result.breaking_news.lower()

    def test_malformed_footnotes_skipped(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        data = json.dumps(
            {
                "breaking_news": "Test",
                "tech_stacks": "Test",
                "new_software": "Test",
                "deep_dives": "Test",
                "footnotes": [
                    {"title": "Good", "url": "https://example.com"},
                    {"title": "", "url": ""},
                    "not a dict",
                    {"title": "No URL"},
                ],
            }
        )
        client.chat.completions.create.return_value = _make_mock_response(data)

        result = generate_report(config, client, sample_emails)
        assert len(result.footnotes) == 1
        assert result.footnotes[0].title == "Good"
