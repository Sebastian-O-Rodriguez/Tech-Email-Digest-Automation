"""Fetch and extract article content from links found in emails."""

from __future__ import annotations

import base64
import json
import logging
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from email_ingester.models import ArticleContent, Email

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; EmailDigestBot/1.0)"

_SKIP_DOMAINS = frozenset(
    [
        "github.com",
        "youtube.com",
        "reddit.com",
        "substack.com",
    ]
)

_SKIP_PATTERNS = [
    # Unsubscribe / opt-out
    r"unsubscribe",
    r"opt-out",
    # Social share links
    r"twitter\.com/intent",
    r"facebook\.com/sharer",
    r"linkedin\.com/share(?:Article)?",
    # Tracking redirects
    r"click\.\w+\.\w+",
    r"list-manage\.com",
    r"mailchimp\.com",
]

_PAYWALL_PHRASES = [
    "subscribe to read",
    "sign in to continue",
    "premium content",
    "paywall",
    "members only",
]

_STRIP_TAGS = ["script", "style", "nav", "footer", "aside", "header"]

_TITLE_SUFFIX_RE = re.compile(r"\s*[|\-–—]\s+.+$")


def _is_skippable(url: str) -> bool:
    """Return True if the URL should be skipped (non-article, tracking, etc.)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return True

    if parsed.scheme not in ("http", "https"):
        return True
    if not parsed.netloc:
        return True

    hostname = parsed.netloc.lower().removeprefix("www.")
    if hostname in _SKIP_DOMAINS:
        return True

    lower = url.lower()
    return any(re.search(pattern, lower) for pattern in _SKIP_PATTERNS)


def filter_links(urls: list[str]) -> list[str]:
    """Return only URLs that look like fetchable article pages.

    Resolves newsletter redirect URLs (e.g. Substack) to their real
    destinations first, then drops mailto:, anchor-only, known skip
    domains, social share links, tracking redirects, and unsubscribe
    patterns. Unresolvable redirect URLs are dropped.
    """
    filtered: list[str] = []

    for url in urls:
        url = url.strip()
        if not url:
            continue

        # Drop non-HTTP schemes (mailto:, etc.) and bare anchors
        if url.startswith("#") or url.startswith("mailto:"):
            continue

        # Resolve newsletter redirects to real destination URLs
        resolved = _resolve_redirect(url)

        if _is_skippable(resolved):
            logger.debug("filter_links: skipping %s", resolved[:100])
            continue

        filtered.append(resolved)

    return filtered


def detect_paywall(response_status: int, html: str) -> bool:
    """Return True if the response looks like a paywall or login wall."""
    if response_status in (402, 403):
        return True

    lower_html = html.lower()
    return any(phrase in lower_html for phrase in _PAYWALL_PHRASES)


def extract_article_text(html: str) -> tuple[str, str]:
    """Return (title, clean_text) extracted from article HTML.

    Strips structural/noise tags, collapses whitespace, and truncates
    text to 500 characters. Returns ("", "") on any extraction failure.
    """
    if not html or not html.strip():
        return ("", "")

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        logger.debug("extract_article_text: failed to parse HTML")
        return ("", "")

    # --- Title ---
    title = ""
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        title = title_tag.get_text(strip=True)
    else:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    # Strip site-name suffix (e.g., " | TechCrunch", " - The Verge")
    if title:
        title = _TITLE_SUFFIX_RE.sub("", title).strip()

    # --- Body text ---
    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    raw_text = soup.get_text(separator="\n")
    lines = (line.strip() for line in raw_text.splitlines())
    clean_text = "\n".join(line for line in lines if line)

    # Truncate to 500 chars
    if len(clean_text) > 500:
        clean_text = clean_text[:500]

    return (title, clean_text)


def _resolve_substack_redirect(url: str) -> str | None:
    """Extract the real destination URL from a Substack redirect link.

    Substack uses two redirect formats:
    1. /redirect/2/<base64-jwt> — the JWT payload has an "e" field with the URL
    2. /redirect/<uuid>?j=<base64> — opaque; we can't extract the URL, skip it

    Returns the destination URL for format 1, or None if not resolvable.
    """
    parsed = urlparse(url)
    if "substack.com" not in parsed.netloc:
        return None

    path_parts = parsed.path.strip("/").split("/")
    # Format: /redirect/2/<jwt-like-token>
    if len(path_parts) == 3 and path_parts[0] == "redirect" and path_parts[1] == "2":
        token = path_parts[2]
        # JWT has 3 dot-separated parts; the payload is the second
        jwt_parts = token.split(".")
        if len(jwt_parts) >= 2:
            try:
                # Add padding for base64url decoding
                payload = jwt_parts[1]
                payload += "=" * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                data = json.loads(decoded)
                dest = data.get("e")
                if dest and dest.startswith("http"):
                    logger.debug("_resolve_substack_redirect: %s -> %s", url[:80], dest)
                    return dest
            except Exception:
                logger.debug("_resolve_substack_redirect: failed to decode JWT for %s", url[:80])
    return None


def _resolve_redirect(url: str) -> str:
    """Resolve newsletter redirect URLs to their real destinations.

    Currently handles Substack redirects. Falls back to the original URL.
    """
    resolved = _resolve_substack_redirect(url)
    return resolved if resolved else url


def fetch_articles(emails: list[Email]) -> list[ArticleContent]:
    """Fetch article content for links found across all emails.

    - Collects links from each email (1-based email_index).
    - Filters via filter_links().
    - Caps total URLs at 10.
    - Fetches each URL synchronously with a 10s timeout.
    - Skips non-HTML responses, paywalled content, and empty extractions.
    - Best-effort: exceptions per URL are logged and skipped.
    """
    # Collect (url, email_index) pairs, preserving first-seen email for dupes
    seen_urls: set[str] = set()
    candidates: list[tuple[str, int]] = []

    for idx, email in enumerate(emails, start=1):
        for url in filter_links(email.links):
            if url not in seen_urls:
                seen_urls.add(url)
                candidates.append((url, idx))

    # Cap at 10 total
    candidates = candidates[:10]

    if not candidates:
        logger.info("fetch_articles: no fetchable links found")
        return []

    logger.info("fetch_articles: fetching %d URLs", len(candidates))

    articles: list[ArticleContent] = []
    headers = {"User-Agent": _USER_AGENT}

    for url, email_index in candidates:
        try:
            response = httpx.get(
                url,
                headers=headers,
                timeout=10.0,
                follow_redirects=True,
            )
        except Exception as exc:
            logger.warning("fetch_articles: failed to fetch %s: %s", url, exc)
            continue

        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            logger.debug(
                "fetch_articles: skipping non-HTML response for %s (content-type: %s)",
                url,
                content_type,
            )
            continue

        html = response.text

        if detect_paywall(response.status_code, html):
            logger.info("fetch_articles: paywall detected for %s", url)
            continue

        try:
            title, text = extract_article_text(html)
        except Exception as exc:
            logger.warning("fetch_articles: extraction error for %s: %s", url, exc)
            continue

        if not title and not text:
            logger.debug("fetch_articles: empty extraction for %s, skipping", url)
            continue

        articles.append(
            ArticleContent(
                url=url,
                title=title,
                text=text,
                email_index=email_index,
            )
        )
        logger.info("fetch_articles: extracted article from %s (email %d)", url, email_index)

    logger.info("fetch_articles: returned %d articles", len(articles))
    return articles
