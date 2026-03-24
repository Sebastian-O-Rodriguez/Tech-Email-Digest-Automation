"""Tests for digest generation."""

from datetime import UTC, datetime

from email_ingester.digest import generate_digest
from email_ingester.models import DigestReport, Email, Footnote


def _make_report() -> DigestReport:
    return DigestReport(
        breaking_news="Major outage on AWS [1].",
        tech_stacks="React 20 ships server components [2].",
        new_software="Cursor launched v2.",
        deep_dives="Great article on system design.",
        footnotes=[
            Footnote(index=1, title="AWS outage", url="https://example.com/outage"),
            Footnote(index=2, title="React 20", url="https://example.com/react20"),
        ],
        source_indices=[1],
    )


def _make_email() -> Email:
    return Email(
        id="msg-001",
        subject="Test Subject",
        sender="sender@example.com",
        timestamp=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
        body_text="Body text.",
        body_html="",
        links=[],
    )


class TestGenerateDigest:
    def test_generates_html_with_sections(self):
        report = _make_report()
        digest = generate_digest(report, total_processed=5, source_emails=[_make_email()])
        assert "Breaking News" in digest.html
        assert "Tech Stacks" in digest.html
        assert "New Software" in digest.html
        assert "Deep Dives" in digest.html
        assert digest.total_processed == 5

    def test_html_contains_inline_footnote_links(self):
        report = _make_report()
        digest = generate_digest(report, total_processed=3, source_emails=[])
        assert "fn-ref" in digest.html
        assert "https://example.com/outage" in digest.html

    def test_html_contains_source_email_links(self):
        report = _make_report()
        email = _make_email()
        digest = generate_digest(report, total_processed=1, source_emails=[email])
        assert "Source Emails" in digest.html
        assert "outlook.office365.com" in digest.html
        assert "Test Subject" in digest.html

    def test_source_emails_filtered_to_referenced_only(self):
        report = DigestReport(
            breaking_news="Test [1]",
            tech_stacks="",
            new_software="",
            deep_dives="",
            footnotes=[Footnote(index=1, title="T", url="https://x.com")],
            source_indices=[2],
        )
        email1 = _make_email()
        email2 = Email(
            id="msg-002",
            subject="Referenced Email",
            sender="s@x.com",
            timestamp=datetime(2026, 3, 23, tzinfo=UTC),
            body_text="",
            body_html="",
            links=[],
        )
        digest = generate_digest(report, total_processed=2, source_emails=[email1, email2])
        assert "Referenced Email" in digest.html
        assert "Test Subject" not in digest.html

    def test_empty_report(self):
        report = DigestReport(
            breaking_news="",
            tech_stacks="",
            new_software="",
            deep_dives="",
        )
        digest = generate_digest(report, total_processed=0, source_emails=[])
        assert digest.total_processed == 0

    def test_report_data_preserved(self):
        report = _make_report()
        digest = generate_digest(report, total_processed=10, source_emails=[])
        assert digest.report is report
