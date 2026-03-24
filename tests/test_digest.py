"""Tests for digest generation."""

from datetime import UTC, datetime

from email_ingester.digest import generate_digest
from email_ingester.models import Email, ProcessedEmail


def _make_item(priority: str, subject: str = "Test Subject") -> ProcessedEmail:
    email = Email(
        id=f"msg-{priority}",
        subject=subject,
        sender="sender@example.com",
        timestamp=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
        body_text="Body text here.",
        body_html="<p>Body text here.</p>",
        links=["https://example.com"],
    )
    return ProcessedEmail(
        email=email,
        summary=f"Summary for {priority} item.",
        priority=priority,
        why_it_matters="Matters because it does.",
        recommended_action="Read it.",
        key_links=["https://example.com"],
        score=0.5,
    )


class TestGenerateDigest:
    def test_splits_by_priority(self):
        items = [_make_item("high"), _make_item("medium"), _make_item("low")]
        digest = generate_digest(items)
        assert len(digest.high_priority) == 1
        assert len(digest.medium_priority) == 1
        assert digest.low_priority_count == 1
        assert digest.total_processed == 3

    def test_generates_html(self):
        items = [_make_item("high")]
        digest = generate_digest(items)
        assert "Email Digest" in digest.html
        assert "Test Subject" in digest.html

    def test_empty_input(self):
        digest = generate_digest([])
        assert digest.total_processed == 0
        assert digest.high_priority == []
        assert digest.medium_priority == []
        assert digest.low_priority_count == 0
        assert "Email Digest" in digest.html
