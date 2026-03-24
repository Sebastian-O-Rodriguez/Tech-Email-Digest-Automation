"""Tests for email content processing."""

from datetime import UTC, datetime

from email_ingester.models import Email
from email_ingester.processor import extract_links, normalize_html, process_email


class TestNormalizeHtml:
    def test_strips_tags(self):
        result = normalize_html("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result

    def test_removes_script_tags(self):
        html = "<p>Text</p><script>alert('xss')</script>"
        assert "alert" not in normalize_html(html)

    def test_removes_style_tags(self):
        html = "<style>.red{color:red}</style><p>Text</p>"
        assert normalize_html(html) == "Text"

    def test_empty_input(self):
        assert normalize_html("") == ""

    def test_preserves_text_content(self):
        html = "<div><h1>Title</h1><p>Paragraph one.</p><p>Paragraph two.</p></div>"
        result = normalize_html(html)
        assert "Title" in result
        assert "Paragraph one." in result
        assert "Paragraph two." in result

    def test_whitespace_only_input_returns_empty(self):
        assert normalize_html("   \n\t  ") == ""

    def test_plain_text_without_tags_returned_as_is(self):
        result = normalize_html("Just plain text with no tags.")
        assert result == "Just plain text with no tags."


class TestExtractLinks:
    def test_extracts_http_links(self):
        html = '<a href="https://example.com">Link</a>'
        assert extract_links(html) == ["https://example.com"]

    def test_skips_non_http(self):
        html = '<a href="mailto:user@example.com">Email</a>'
        assert extract_links(html) == []

    def test_deduplicates(self):
        html = '<a href="https://example.com">A</a><a href="https://example.com">B</a>'
        assert extract_links(html) == ["https://example.com"]

    def test_filters_unsubscribe(self):
        html = '<a href="https://example.com/unsubscribe">Unsub</a>'
        assert extract_links(html) == []

    def test_empty_input(self):
        assert extract_links("") == []

    def test_skips_relative_urls(self):
        html = '<a href="/about">About</a>'
        assert extract_links(html) == []

    def test_skips_empty_href(self):
        html = '<a href="">Click</a>'
        assert extract_links(html) == []

    def test_skips_malformed_url_without_netloc(self):
        # A URL that parses but has no netloc (treated as relative)
        html = '<a href="not-a-url">Bad link</a>'
        assert extract_links(html) == []


class TestProcessEmail:
    def test_enriches_email(self):
        email = Email(
            id="test-1",
            subject="Test",
            sender="test@example.com",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            body_text="",
            body_html='<p>Hello</p><a href="https://example.com">Link</a>',
            links=[],
        )
        result = process_email(email)
        assert "Hello" in result.body_text
        assert result.links == ["https://example.com"]
        assert result.id == email.id  # Unchanged fields preserved
