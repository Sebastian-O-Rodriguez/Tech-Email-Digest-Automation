"""Shared test fixtures."""

from datetime import UTC, datetime

import pytest

from email_ingester.models import Email, ProcessedEmail


@pytest.fixture
def sample_email() -> Email:
    return Email(
        id="msg-001",
        subject="Weekly AI Research Roundup",
        sender="newsletter@example.com",
        timestamp=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
        body_text="This week in AI: new breakthroughs in reasoning models.",
        body_html=(
            "<p>This week in AI: new breakthroughs in reasoning models.</p>"
            '<a href="https://example.com/article">Read more</a>'
        ),
        links=["https://example.com/article"],
    )


@pytest.fixture
def sample_processed(sample_email: Email) -> ProcessedEmail:
    return ProcessedEmail(
        email=sample_email,
        summary="Weekly roundup covering reasoning model advances.",
        priority="high",
        why_it_matters="Relevant to current AI development work.",
        recommended_action="Read the linked article.",
        key_links=["https://example.com/article"],
        score=0.0,
    )
