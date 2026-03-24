"""Tests for digest generation."""

from datetime import UTC, datetime

from email_ingester.digest import generate_digest
from email_ingester.models import DigestReport, Email


def _make_report() -> DigestReport:
    return DigestReport(
        breaking_news="Major outage on AWS [1].",
        tech_stacks="React 20 ships server components [2].",
        new_software="Cursor launched v2.",
        deep_dives="Great article on system design.",
        source_indices=[1, 2],
    )


def _make_emails() -> list[Email]:
    return [
        Email(
            id="msg-001",
            subject="AWS Outage Alert",
            sender="alerts@example.com",
            timestamp=datetime(2026, 3, 23, 10, 0, tzinfo=UTC),
            body_text="Body text.",
            body_html="",
            links=[],
        ),
        Email(
            id="msg-002",
            subject="React 20 Released",
            sender="news@example.com",
            timestamp=datetime(2026, 3, 23, 11, 0, tzinfo=UTC),
            body_text="Body text.",
            body_html="",
            links=[],
        ),
    ]


class TestGenerateDigest:
    def test_generates_html_with_sections(self):
        report = _make_report()
        digest = generate_digest(report, total_processed=5, source_emails=_make_emails())
        assert "Breaking News" in digest.html
        assert "Tech Stacks" in digest.html
        assert digest.total_processed == 5

    def test_inline_refs_link_to_outlook(self):
        report = _make_report()
        digest = generate_digest(report, total_processed=2, source_emails=_make_emails())
        assert "src-ref" in digest.html
        assert "outlook.office365.com" in digest.html

    def test_sources_section_shows_referenced_emails(self):
        report = _make_report()
        emails = _make_emails()
        digest = generate_digest(report, total_processed=2, source_emails=emails)
        assert "Sources" in digest.html
        assert "AWS Outage Alert" in digest.html
        assert "React 20 Released" in digest.html

    def test_only_referenced_emails_in_sources(self):
        report = DigestReport(
            breaking_news="Test [2]",
            tech_stacks="",
            new_software="",
            deep_dives="",
            source_indices=[2],
        )
        emails = _make_emails()
        digest = generate_digest(report, total_processed=2, source_emails=emails)
        assert "React 20 Released" in digest.html
        assert "AWS Outage Alert" not in digest.html

    def test_empty_report(self):
        report = DigestReport(
            breaking_news="",
            tech_stacks="",
            new_software="",
            deep_dives="",
        )
        digest = generate_digest(report, total_processed=0, source_emails=[])
        assert digest.total_processed == 0
