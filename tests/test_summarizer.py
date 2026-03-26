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
            "strategic_intel": "AWS us-east-1 experienced a major outage [1].",
            "engineering": "React 20 ships server components by default [2].",
            "tools_and_ops": "No notable releases this cycle.",
            "radar": "No deep dives worth flagging.",
            "sources": [1, 2],
        }
    )


class TestGenerateReport:
    def test_successful_report(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.return_value = _make_mock_response(_valid_report_json())

        result = generate_report(config, client, sample_emails)

        assert isinstance(result, DigestReport)
        assert "outage" in result.strategic_intel.lower()
        assert "react" in result.engineering.lower()
        assert result.source_indices == [1, 2]

    def test_api_error_returns_fallback(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.side_effect = openai.APIStatusError(
            message="Internal Server Error",
            response=MagicMock(status_code=500),
            body={},
        )

        result = generate_report(config, client, sample_emails)

        assert isinstance(result, DigestReport)
        assert "failed" in result.strategic_intel.lower()

    def test_json_parse_error_returns_fallback(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.return_value = _make_mock_response("not json {{")

        result = generate_report(config, client, sample_emails)
        assert "failed" in result.strategic_intel.lower()

    def test_empty_choices_returns_fallback(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        response = MagicMock()
        response.choices = []
        client.chat.completions.create.return_value = response

        result = generate_report(config, client, sample_emails)
        assert "failed" in result.strategic_intel.lower()

    def test_blank_response_returns_fallback(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        client.chat.completions.create.return_value = _make_mock_response("   ")

        result = generate_report(config, client, sample_emails)
        assert "failed" in result.strategic_intel.lower()

    def test_non_int_sources_skipped(self, config: Config, sample_emails: list[Email]):
        client = MagicMock(spec=openai.OpenAI)
        data = json.dumps(
            {
                "strategic_intel": "Test [1]",
                "engineering": "",
                "tools_and_ops": "",
                "radar": "",
                "sources": [1, "bad", None, 2],
            }
        )
        client.chat.completions.create.return_value = _make_mock_response(data)

        result = generate_report(config, client, sample_emails)
        assert result.source_indices == [1, 2]
