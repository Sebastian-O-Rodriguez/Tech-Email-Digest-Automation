"""Generate HTML digest from the aggregated report using Jinja2."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from email_ingester.models import DigestOutput, DigestReport, Email

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _outlook_url(message_id: str) -> str:
    """Build an Outlook Web deep link for a message ID."""
    encoded = quote(message_id, safe="")
    return f"https://outlook.office365.com/mail/id/{encoded}"


def _linkify_sources(text: str, emails: list[Email]) -> Markup:
    """Replace [1], [2] etc. in text with clickable links to source emails.

    The numbers are 1-based indices into the full emails list (as sent to the LLM).
    """

    def _replace(match: re.Match) -> str:
        num = int(match.group(1))
        if 1 <= num <= len(emails):
            url = _outlook_url(emails[num - 1].id)
            return f'<a class="src-ref" href="{url}">[{num}]</a>'
        return match.group(0)

    result = re.sub(r"\[(\d+)\]", _replace, text)
    return Markup(result)


def generate_digest(
    report: DigestReport, total_processed: int, source_emails: list[Email]
) -> DigestOutput:
    """Render the report into an HTML digest.

    source_emails is the full list of processed emails (matching the indices
    the LLM used). Only emails referenced in source_indices appear in the
    Sources section at the bottom.
    """
    # Filter to only referenced emails for the Sources section
    referenced = []
    for idx in report.source_indices:
        if 1 <= idx <= len(source_emails):
            referenced.append((idx, source_emails[idx - 1]))

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    env.globals["outlook_url"] = _outlook_url
    env.globals["linkify_sources"] = lambda text: _linkify_sources(text, source_emails)

    digest = DigestOutput(
        generated_at=datetime.now(UTC),
        total_processed=total_processed,
        report=report,
        source_emails=[email for _, email in referenced],
    )

    html = template = env.get_template("digest.html.j2")
    html = template.render(digest=digest, referenced=referenced)

    return DigestOutput(
        generated_at=digest.generated_at,
        total_processed=digest.total_processed,
        report=digest.report,
        source_emails=digest.source_emails,
        html=html,
    )
