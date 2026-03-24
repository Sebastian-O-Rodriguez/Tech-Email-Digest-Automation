"""Normalize email content: HTML to text, link extraction."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from email_ingester.models import Email

logger = logging.getLogger(__name__)


def normalize_html(html: str) -> str:
    """Convert HTML to clean plain text."""
    if not html or not html.strip():
        return ""

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        logger.warning("Failed to parse HTML, returning stripped text")
        return html.strip()

    # Remove script and style elements
    for tag in soup(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator="\n")

    # Collapse whitespace
    lines = (line.strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def extract_links(html: str) -> list[str]:
    """Extract unique, valid HTTP(S) URLs from HTML."""
    if not html or not html.strip():
        return []
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []

    for anchor in soup.find_all("a", href=True):
        raw = anchor.get("href", "")
        if not isinstance(raw, str):
            logger.debug("Skipping non-string href: %r", raw)
            continue

        url = raw.strip()
        if not url or url in seen:
            continue

        try:
            parsed = urlparse(url)
        except ValueError:
            logger.debug("Skipping malformed URL: %s", url)
            continue

        if parsed.scheme not in ("http", "https"):
            continue
        if not parsed.netloc:
            continue
        if _is_junk_link(url):
            continue

        seen.add(url)
        links.append(url)

    return links


def _is_junk_link(url: str) -> bool:
    """Filter out tracking pixels, unsubscribe links, and other noise."""
    junk_patterns = [
        r"unsubscribe",
        r"opt-out",
        r"email-tracking",
        r"click\.\w+\.com",
        r"list-manage\.com",
        r"mailchimp\.com/track",
    ]
    lower = url.lower()
    return any(re.search(pattern, lower) for pattern in junk_patterns)


def process_email(email: Email) -> Email:
    """Enrich an email with cleaned text and extracted links."""
    return replace(
        email,
        body_text=normalize_html(email.body_html),
        links=extract_links(email.body_html),
    )
