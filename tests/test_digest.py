"""Tests for digest generation."""

from datetime import UTC, datetime

from email_ingester.digest import generate_digest
from email_ingester.models import Email, ProcessedEmail


def _make_item(topic: str, subject: str = "Test Subject") -> ProcessedEmail:
    email = Email(
        id=f"msg-{topic}",
        subject=subject,
        sender="sender@example.com",
        timestamp=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
        body_text="Body text here.",
        body_html="<p>Body text here.</p>",
        links=["https://example.com"],
    )
    return ProcessedEmail(
        email=email,
        summary=f"Summary for {topic} item.",
        topic=topic,
        key_links=["https://example.com"],
        score=0.5,
    )


class TestGenerateDigest:
    def test_groups_by_topic(self):
        items = [
            _make_item("breaking_news"),
            _make_item("tech_stacks"),
            _make_item("new_software"),
            _make_item("deep_dives"),
        ]
        digest = generate_digest(items)
        assert len(digest.breaking_news) == 1
        assert len(digest.tech_stacks) == 1
        assert len(digest.new_software) == 1
        assert len(digest.deep_dives) == 1
        assert digest.total_processed == 4

    def test_generates_html(self):
        items = [_make_item("breaking_news")]
        digest = generate_digest(items)
        assert "Email Digest" in digest.html
        assert "Test Subject" in digest.html
        assert "Breaking News" in digest.html

    def test_empty_input(self):
        digest = generate_digest([])
        assert digest.total_processed == 0
        assert digest.breaking_news == []
        assert digest.tech_stacks == []
        assert digest.new_software == []
        assert digest.deep_dives == []
        assert "Email Digest" in digest.html

    def test_html_contains_link_buttons(self):
        items = [_make_item("tech_stacks")]
        digest = generate_digest(items)
        assert 'class="btn"' in digest.html
        assert "https://example.com" in digest.html
