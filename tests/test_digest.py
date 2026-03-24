"""Tests for digest generation."""

from email_ingester.digest import generate_digest
from email_ingester.models import DigestReport, Footnote


def _make_report() -> DigestReport:
    return DigestReport(
        breaking_news="Major outage on AWS.",
        tech_stacks="React 20 ships server components.",
        new_software="Cursor launched v2.",
        deep_dives="Great article on system design.",
        footnotes=[
            Footnote(title="AWS outage", url="https://example.com/outage"),
        ],
    )


class TestGenerateDigest:
    def test_generates_html_with_sections(self):
        report = _make_report()
        digest = generate_digest(report, total_processed=5)
        assert "Guava AI" in digest.html
        assert "Breaking News" in digest.html
        assert "Tech Stacks" in digest.html
        assert "New Software" in digest.html
        assert "Deep Dives" in digest.html
        assert digest.total_processed == 5

    def test_html_contains_footnotes(self):
        report = _make_report()
        digest = generate_digest(report, total_processed=3)
        assert "AWS outage" in digest.html
        assert "https://example.com/outage" in digest.html

    def test_empty_report(self):
        report = DigestReport(
            breaking_news="",
            tech_stacks="",
            new_software="",
            deep_dives="",
        )
        digest = generate_digest(report, total_processed=0)
        assert digest.total_processed == 0
        assert "Guava AI" in digest.html

    def test_report_data_preserved(self):
        report = _make_report()
        digest = generate_digest(report, total_processed=10)
        assert digest.report is report
        assert digest.report.breaking_news == "Major outage on AWS."
