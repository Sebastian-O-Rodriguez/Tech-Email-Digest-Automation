"""Tests for article fetching, filtering, and extraction."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest  # noqa: F401 — keep for potential future fixture use

from email_ingester.article_fetcher import (
    detect_paywall,
    extract_article_text,
    fetch_articles,
    filter_links,
)
from email_ingester.models import ArticleContent, Email
from email_ingester.summarizer import _format_emails_for_llm

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_email(
    *,
    idx: str = "msg-001",
    links: list[str] | None = None,
) -> Email:
    return Email(
        id=idx,
        subject="Test Newsletter",
        sender="sender@example.com",
        timestamp=datetime(2026, 3, 26, 9, 0, tzinfo=UTC),
        body_text="Some newsletter body text.",
        body_html="<p>Some newsletter body text.</p>",
        links=links or [],
    )


def _make_httpx_response(
    *,
    status_code: int = 200,
    content_type: str = "text/html; charset=utf-8",
    text: str = "<html><head><title>Article</title></head><body><p>Body text.</p></body></html>",
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": content_type}
    response.text = text
    return response


# ---------------------------------------------------------------------------
# filter_links
# ---------------------------------------------------------------------------


class TestFilterLinks:
    def test_keeps_valid_article_url(self):
        urls = ["https://techcrunch.com/2026/03/ai-funding"]
        assert filter_links(urls) == ["https://techcrunch.com/2026/03/ai-funding"]

    def test_keeps_http_url(self):
        urls = ["http://example.com/article"]
        assert filter_links(urls) == ["http://example.com/article"]

    def test_filters_mailto(self):
        urls = ["mailto:user@example.com"]
        assert filter_links(urls) == []

    def test_filters_anchor_only(self):
        urls = ["#section-1"]
        assert filter_links(urls) == []

    def test_filters_twitter_intent(self):
        urls = ["https://twitter.com/intent/tweet?text=hello"]
        assert filter_links(urls) == []

    def test_filters_facebook_sharer(self):
        urls = ["https://facebook.com/sharer/sharer.php?u=https://example.com"]
        assert filter_links(urls) == []

    def test_filters_linkedin_share(self):
        urls = ["https://linkedin.com/shareArticle?mini=true&url=https://example.com"]
        assert filter_links(urls) == []

    def test_filters_linkedin_share_variant(self):
        urls = ["https://linkedin.com/share?url=https://example.com"]
        assert filter_links(urls) == []

    def test_filters_github_domain(self):
        urls = ["https://github.com/owner/repo"]
        assert filter_links(urls) == []

    def test_filters_youtube_domain(self):
        urls = ["https://youtube.com/watch?v=abc123"]
        assert filter_links(urls) == []

    def test_filters_reddit_domain(self):
        urls = ["https://reddit.com/r/programming"]
        assert filter_links(urls) == []

    def test_filters_unsubscribe_link(self):
        urls = ["https://example.com/unsubscribe?token=abc"]
        assert filter_links(urls) == []

    def test_filters_opt_out_link(self):
        urls = ["https://example.com/email/opt-out"]
        assert filter_links(urls) == []

    def test_filters_tracking_click_redirect(self):
        urls = ["https://click.example.com/track?url=https://real.com"]
        assert filter_links(urls) == []

    def test_filters_list_manage(self):
        urls = ["https://list-manage.com/track/click?u=abc"]
        assert filter_links(urls) == []

    def test_filters_mailchimp(self):
        urls = ["https://mailchimp.com/track/click?id=abc"]
        assert filter_links(urls) == []

    def test_empty_input_returns_empty(self):
        assert filter_links([]) == []

    def test_mixed_input_keeps_only_valid(self):
        urls = [
            "https://techcrunch.com/article",
            "mailto:spam@example.com",
            "https://github.com/some/repo",
            "https://arstechnica.com/another",
            "#anchor",
            "https://twitter.com/intent/retweet",
        ]
        result = filter_links(urls)
        assert result == [
            "https://techcrunch.com/article",
            "https://arstechnica.com/another",
        ]

    def test_non_http_scheme_filtered(self):
        urls = ["ftp://files.example.com/report.pdf"]
        assert filter_links(urls) == []

    def test_www_prefix_stripped_for_domain_check(self):
        urls = ["https://www.github.com/owner/repo"]
        assert filter_links(urls) == []

    def test_whitespace_stripped_from_url(self):
        urls = ["  https://example.com/article  "]
        assert filter_links(urls) == ["https://example.com/article"]


# ---------------------------------------------------------------------------
# detect_paywall
# ---------------------------------------------------------------------------


class TestDetectPaywall:
    def test_returns_true_for_402(self):
        assert detect_paywall(402, "") is True

    def test_returns_true_for_403(self):
        assert detect_paywall(403, "") is True

    def test_returns_true_for_subscribe_to_read(self):
        html = "<p>Subscribe to read the full article.</p>"
        assert detect_paywall(200, html) is True

    def test_returns_true_case_insensitive(self):
        html = "<p>SUBSCRIBE TO READ more premium content.</p>"
        assert detect_paywall(200, html) is True

    def test_returns_true_for_members_only(self):
        html = "<div class='wall'>Members only content</div>"
        assert detect_paywall(200, html) is True

    def test_returns_true_for_sign_in_to_continue(self):
        html = "<p>Sign in to continue reading.</p>"
        assert detect_paywall(200, html) is True

    def test_returns_true_for_premium_content(self):
        html = "<span>This is premium content</span>"
        assert detect_paywall(200, html) is True

    def test_returns_true_for_paywall_keyword(self):
        html = "<div id='paywall'>You have reached your article limit.</div>"
        assert detect_paywall(200, html) is True

    def test_returns_false_for_normal_article(self):
        html = "<article><p>Here is the full article text about AI trends.</p></article>"
        assert detect_paywall(200, html) is False

    def test_returns_false_for_empty_body_with_200(self):
        assert detect_paywall(200, "") is False

    def test_returns_false_for_200_with_no_paywall_phrases(self):
        html = "<html><body><h1>Breaking News</h1><p>Content here.</p></body></html>"
        assert detect_paywall(200, html) is False


# ---------------------------------------------------------------------------
# extract_article_text
# ---------------------------------------------------------------------------


class TestExtractArticleText:
    def test_extracts_title_from_title_tag(self):
        html = "<html><head><title>My Article</title></head><body><p>Text.</p></body></html>"
        title, _ = extract_article_text(html)
        assert title == "My Article"

    def test_falls_back_to_h1_when_no_title_tag(self):
        html = "<html><body><h1>Fallback Heading</h1><p>Text.</p></body></html>"
        title, _ = extract_article_text(html)
        assert title == "Fallback Heading"

    def test_strips_site_name_suffix_pipe(self):
        html = (
            "<html><head><title>Great Article | TechCrunch</title></head>"
            "<body><p>Text.</p></body></html>"
        )
        title, _ = extract_article_text(html)
        assert title == "Great Article"
        assert "TechCrunch" not in title

    def test_strips_site_name_suffix_dash(self):
        html = (
            "<html><head><title>My Post - The Verge</title></head><body><p>Text.</p></body></html>"
        )
        title, _ = extract_article_text(html)
        assert title == "My Post"

    def test_strips_site_name_suffix_em_dash(self):
        html = "<html><head><title>Feature — Wired</title></head><body><p>Text.</p></body></html>"
        title, _ = extract_article_text(html)
        assert title == "Feature"

    def test_strips_script_tags_from_text(self):
        html = "<html><body><p>Article</p><script>var x = 1;</script></body></html>"
        _, text = extract_article_text(html)
        assert "var x" not in text
        assert "Article" in text

    def test_strips_style_tags_from_text(self):
        html = "<html><body><style>body{color:red}</style><p>Content</p></body></html>"
        _, text = extract_article_text(html)
        assert "color:red" not in text
        assert "Content" in text

    def test_strips_nav_tags_from_text(self):
        html = "<html><body><nav>Home | About | Contact</nav><p>Article body.</p></body></html>"
        _, text = extract_article_text(html)
        assert "About" not in text
        assert "Article body." in text

    def test_strips_footer_tags_from_text(self):
        html = "<html><body><p>Main content.</p><footer>Copyright 2026</footer></body></html>"
        _, text = extract_article_text(html)
        assert "Copyright" not in text
        assert "Main content." in text

    def test_strips_aside_tags_from_text(self):
        html = "<html><body><p>Main.</p><aside>Related stories</aside></body></html>"
        _, text = extract_article_text(html)
        assert "Related stories" not in text

    def test_strips_header_tags_from_text(self):
        html = "<html><body><header>Site Header</header><p>Article.</p></body></html>"
        _, text = extract_article_text(html)
        assert "Site Header" not in text

    def test_truncates_text_to_500_chars(self):
        long_content = "word " * 200  # 1000 chars
        html = f"<html><body><p>{long_content}</p></body></html>"
        _, text = extract_article_text(html)
        assert len(text) <= 500

    def test_short_text_not_truncated(self):
        html = "<html><body><p>Short text.</p></body></html>"
        _, text = extract_article_text(html)
        assert text == "Short text."

    def test_returns_empty_tuple_for_empty_string(self):
        assert extract_article_text("") == ("", "")

    def test_returns_empty_tuple_for_whitespace_only(self):
        assert extract_article_text("   \n\t  ") == ("", "")

    def test_empty_title_tag_falls_back_to_h1(self):
        html = "<html><head><title></title></head><body><h1>Heading</h1><p>Text.</p></body></html>"
        title, _ = extract_article_text(html)
        assert title == "Heading"


# ---------------------------------------------------------------------------
# fetch_articles (mocked httpx)
# ---------------------------------------------------------------------------


_ARTICLE_HTML = (
    "<html><head><title>Test Article</title></head>"
    "<body><p>This is the article content for testing purposes.</p></body></html>"
)


class TestFetchArticles:
    def test_fetches_articles_from_email_links(self):
        email = _make_email(links=["https://example.com/article"])
        mock_response = _make_httpx_response(text=_ARTICLE_HTML)

        with patch("email_ingester.article_fetcher.httpx.get", return_value=mock_response):
            results = fetch_articles([email])

        assert len(results) == 1
        assert isinstance(results[0], ArticleContent)
        assert results[0].url == "https://example.com/article"
        assert results[0].title == "Test Article"
        assert results[0].email_index == 1

    def test_respects_10_article_cap(self):
        # 12 distinct valid URLs across emails
        urls = [f"https://example.com/article/{i}" for i in range(12)]
        email = _make_email(links=urls)
        mock_response = _make_httpx_response(text=_ARTICLE_HTML)

        patch_target = "email_ingester.article_fetcher.httpx.get"
        with patch(patch_target, return_value=mock_response) as mock_get:
            results = fetch_articles([email])

        assert mock_get.call_count == 10
        assert len(results) == 10

    def test_skips_paywalled_content(self):
        email = _make_email(links=["https://example.com/article"])
        paywall_html = "<html><body><p>Subscribe to read the full article.</p></body></html>"
        mock_response = _make_httpx_response(text=paywall_html)

        with patch("email_ingester.article_fetcher.httpx.get", return_value=mock_response):
            results = fetch_articles([email])

        assert results == []

    def test_skips_non_html_responses(self):
        email = _make_email(links=["https://example.com/file.pdf"])
        mock_response = _make_httpx_response(content_type="application/pdf", text="PDF content")

        with patch("email_ingester.article_fetcher.httpx.get", return_value=mock_response):
            results = fetch_articles([email])

        assert results == []

    def test_handles_httpx_timeout_gracefully(self):
        import httpx

        email = _make_email(links=["https://slow.example.com/article"])

        with patch(
            "email_ingester.article_fetcher.httpx.get",
            side_effect=httpx.TimeoutException("Request timed out"),
        ):
            results = fetch_articles([email])

        assert results == []

    def test_handles_connection_error_gracefully(self):
        import httpx

        email = _make_email(links=["https://unreachable.example.com/article"])

        with patch(
            "email_ingester.article_fetcher.httpx.get",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            results = fetch_articles([email])

        assert results == []

    def test_deduplicates_urls_across_emails(self):
        shared_url = "https://example.com/article"
        email1 = _make_email(idx="msg-001", links=[shared_url])
        email2 = _make_email(idx="msg-002", links=[shared_url])
        mock_response = _make_httpx_response(text=_ARTICLE_HTML)
        patch_target = "email_ingester.article_fetcher.httpx.get"
        with patch(patch_target, return_value=mock_response) as mock_get:
            results = fetch_articles([email1, email2])

        assert mock_get.call_count == 1
        assert len(results) == 1
        # First-seen email index is preserved (email 1)
        assert results[0].email_index == 1

    def test_returns_empty_list_when_no_emails_have_links(self):
        email = _make_email(links=[])
        results = fetch_articles([email])
        assert results == []

    def test_returns_empty_list_for_empty_email_list(self):
        results = fetch_articles([])
        assert results == []

    def test_email_index_reflects_position_in_list(self):
        email1 = _make_email(idx="msg-001", links=[])
        email2 = _make_email(idx="msg-002", links=["https://example.com/article"])
        mock_response = _make_httpx_response(text=_ARTICLE_HTML)

        with patch("email_ingester.article_fetcher.httpx.get", return_value=mock_response):
            results = fetch_articles([email1, email2])

        assert len(results) == 1
        assert results[0].email_index == 2

    def test_skips_links_filtered_by_filter_links(self):
        email = _make_email(links=["https://github.com/owner/repo", "mailto:user@example.com"])

        with patch("email_ingester.article_fetcher.httpx.get") as mock_get:
            results = fetch_articles([email])

        mock_get.assert_not_called()
        assert results == []

    def test_skips_empty_extraction(self):
        # An HTML response that produces no title and no body text
        empty_html = "<html><head></head><body></body></html>"
        email = _make_email(links=["https://example.com/empty"])
        mock_response = _make_httpx_response(text=empty_html)

        with patch("email_ingester.article_fetcher.httpx.get", return_value=mock_response):
            results = fetch_articles([email])

        assert results == []

    def test_handles_general_exception_gracefully(self):
        email = _make_email(links=["https://example.com/article"])

        with patch(
            "email_ingester.article_fetcher.httpx.get",
            side_effect=RuntimeError("Unexpected error"),
        ):
            results = fetch_articles([email])

        assert results == []


# ---------------------------------------------------------------------------
# _format_emails_for_llm integration tests
# ---------------------------------------------------------------------------


class TestFormatEmailsForLlm:
    def test_without_articles_format_unchanged(self):
        email = _make_email(links=["https://example.com/article"])
        result = _format_emails_for_llm([email])

        assert "[1]" in result
        assert "Test Newsletter" in result
        assert "sender@example.com" in result
        assert "Article:" not in result

    def test_with_articles_appended_after_links(self):
        email = _make_email(links=["https://example.com/article"])
        article = ArticleContent(
            url="https://example.com/article",
            title="The Future of AI",
            text="AI is transforming industries.",
            email_index=1,
        )

        result = _format_emails_for_llm([email], articles=[article])

        assert "Article:" in result
        assert "The Future of AI" in result
        assert "AI is transforming industries." in result

    def test_article_line_appears_after_links_line(self):
        email = _make_email(links=["https://example.com/article"])
        article = ArticleContent(
            url="https://example.com/article",
            title="Headline",
            text="Article body.",
            email_index=1,
        )

        result = _format_emails_for_llm([email], articles=[article])
        links_pos = result.index("Links:")
        article_pos = result.index("Article:")

        assert article_pos > links_pos

    def test_multiple_articles_per_email_produce_multiple_lines(self):
        email = _make_email(
            links=[
                "https://example.com/a1",
                "https://example.com/a2",
            ]
        )
        article1 = ArticleContent(
            url="https://example.com/a1",
            title="First Article",
            text="First body.",
            email_index=1,
        )
        article2 = ArticleContent(
            url="https://example.com/a2",
            title="Second Article",
            text="Second body.",
            email_index=1,
        )

        result = _format_emails_for_llm([email], articles=[article1, article2])

        assert result.count("Article:") == 2
        assert "First Article" in result
        assert "Second Article" in result

    def test_articles_from_different_emails_routed_correctly(self):
        email1 = _make_email(idx="msg-001", links=["https://example.com/a1"])
        email2 = _make_email(idx="msg-002", links=["https://example.com/a2"])
        article1 = ArticleContent(
            url="https://example.com/a1",
            title="Email One Article",
            text="Content one.",
            email_index=1,
        )
        article2 = ArticleContent(
            url="https://example.com/a2",
            title="Email Two Article",
            text="Content two.",
            email_index=2,
        )

        result = _format_emails_for_llm([email1, email2], articles=[article1, article2])

        # Split on double newline to isolate per-email blocks
        blocks = result.split("\n\n")
        block1 = blocks[0]
        block2 = blocks[1]

        assert "Email One Article" in block1
        assert "Email Two Article" not in block1
        assert "Email Two Article" in block2
        assert "Email One Article" not in block2

    def test_none_articles_behaves_same_as_no_articles(self):
        email = _make_email(links=["https://example.com/article"])
        result_none = _format_emails_for_llm([email], articles=None)
        result_omitted = _format_emails_for_llm([email])
        assert result_none == result_omitted
