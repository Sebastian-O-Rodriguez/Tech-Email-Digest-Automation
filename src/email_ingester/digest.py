"""Generate HTML digest from the aggregated report using Jinja2."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from email_ingester.models import DigestOutput, DigestReport, Email, Footnote

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _linkify_footnotes(text: str, footnotes: list[Footnote]) -> Markup:
    """Replace [1], [2] etc. in text with clickable superscript links."""
    fn_map = {fn.index: fn.url for fn in footnotes}

    def _replace(match: re.Match) -> str:
        num = int(match.group(1))
        url = fn_map.get(num)
        if url:
            return f'<a class="fn-ref" href="{url}">{num}</a>'
        return match.group(0)

    result = re.sub(r"\[(\d+)\]", _replace, text)
    return Markup(result)


def _outlook_url(message_id: str) -> str:
    """Build an Outlook Web deep link for a message ID."""
    encoded = quote(message_id, safe="")
    return f"https://outlook.office365.com/mail/id/{encoded}"


def generate_digest(
    report: DigestReport, total_processed: int, source_emails: list[Email]
) -> DigestOutput:
    """Render the report into an HTML digest.

    Only emails referenced by the LLM (via source_indices) are included
    in the source emails section.
    """
    # Filter to only referenced emails (indices are 1-based)
    if report.source_indices:
        referenced = []
        for idx in report.source_indices:
            if 1 <= idx <= len(source_emails):
                referenced.append(source_emails[idx - 1])
    else:
        referenced = []

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    env.globals["outlook_url"] = _outlook_url
    env.globals["linkify_footnotes"] = _linkify_footnotes
    template = env.get_template("digest.html.j2")

    digest = DigestOutput(
        generated_at=datetime.now(UTC),
        total_processed=total_processed,
        report=report,
        source_emails=referenced,
    )

    html = template.render(digest=digest)

    return DigestOutput(
        generated_at=digest.generated_at,
        total_processed=digest.total_processed,
        report=digest.report,
        source_emails=digest.source_emails,
        html=html,
    )
