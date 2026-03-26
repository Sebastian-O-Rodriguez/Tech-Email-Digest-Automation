"""Generate HTML digest from the aggregated report using Jinja2."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape

from email_ingester.models import ArticleContent, DigestOutput, DigestReport, Email

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _build_article_url_map(articles: list[ArticleContent]) -> dict[int, str]:
    """Build a mapping of email_index -> best article URL.

    When an email has multiple articles, use the first one (highest relevance).
    """
    url_map: dict[int, str] = {}
    for article in articles:
        if article.email_index not in url_map:
            url_map[article.email_index] = article.url
    return url_map


def _mla_citation(idx: int, email: Email, url: str | None = None) -> str:
    """Format an email as an MLA-style citation, optionally with a hyperlink."""
    date_str = email.timestamp.strftime("%d %b. %Y")
    if url:
        return (
            f"[{idx}] {email.sender}. "
            f'"<a href="{url}" style="color:#2563eb;text-decoration:none;">'
            f'{email.subject}</a>." {date_str}.'
        )
    return f'[{idx}] {email.sender}. "{email.subject}." {date_str}.'


def _render_section(text: str, article_urls: dict[int, str] | None = None) -> Markup:
    """Convert LLM section text into HTML bullet list.

    Source refs like [4] become hyperlinks when an article URL exists for that index.
    """
    if not text or text.strip() == "Nothing notable this cycle.":
        return Markup(f"<p class='section-empty'>{escape(text)}</p>")

    urls = article_urls or {}

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    items = []
    for line in lines:
        safe_line = str(escape(line))
        # Convert **bold** to <strong>
        safe_line = re.sub(
            r"\*\*(.+?)\*\*",
            r"<strong>\1</strong>",
            safe_line,
        )

        # Convert [n] source refs to hyperlinks when we have article URLs
        def _linkify_ref(match: re.Match[str]) -> str:
            idx = int(match.group(1))
            if idx in urls:
                return (
                    f'<a href="{urls[idx]}" '
                    f'style="color:#2563eb;text-decoration:none;font-size:12px;">'
                    f"[{idx}]</a>"
                )
            return match.group(0)

        safe_line = re.sub(r"\[(\d+)\]", _linkify_ref, safe_line)
        items.append(f"<li>{safe_line}</li>")

    return Markup(f"<ul class='section-list'>{''.join(items)}</ul>")


def generate_digest(
    report: DigestReport,
    total_processed: int,
    source_emails: list[Email],
    articles: list[ArticleContent] | None = None,
) -> DigestOutput:
    """Render the report into an HTML digest."""
    article_urls = _build_article_url_map(articles) if articles else {}

    citations = []
    for idx in report.source_indices:
        if 1 <= idx <= len(source_emails):
            url = article_urls.get(idx)
            citations.append(_mla_citation(idx, source_emails[idx - 1], url))

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    env.globals["render_section"] = lambda text: _render_section(text, article_urls)
    template = env.get_template("digest.html.j2")

    digest = DigestOutput(
        generated_at=datetime.now(UTC),
        total_processed=total_processed,
        report=report,
        source_emails=[
            source_emails[idx - 1]
            for idx in report.source_indices
            if 1 <= idx <= len(source_emails)
        ],
    )

    html = template.render(digest=digest, citations=citations, edition="Daily")

    return DigestOutput(
        generated_at=digest.generated_at,
        total_processed=digest.total_processed,
        report=digest.report,
        source_emails=digest.source_emails,
        html=html,
    )
