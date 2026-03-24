"""Shared test fixtures."""

from datetime import UTC, datetime

import pytest

from email_ingester.models import Email


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
