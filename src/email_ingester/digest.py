"""Generate HTML digest from the aggregated report using Jinja2."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape

from email_ingester.models import DigestOutput, DigestReport, Email

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _mla_citation(idx: int, email: Email) -> str:
    """Format an email as an MLA-style citation."""
    date_str = email.timestamp.strftime("%d %b. %Y")
    return f'[{idx}] {email.sender}. "{email.subject}." {date_str}.'


def _render_section(text: str) -> Markup:
    """Convert LLM section text into HTML bullet list.

    Input:  "**Deno 2.1** drops compat layer [4]\\n**Bun** adds S3 client [7]"
    Output: <ul><li><strong>Deno 2.1</strong> drops compat layer [4]</li>...</ul>
    """
    if not text or text.strip() == "Nothing notable this cycle.":
        return Markup(f"<p class='section-empty'>{escape(text)}</p>")

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
        items.append(f"<li>{safe_line}</li>")

    return Markup(f"<ul class='section-list'>{''.join(items)}</ul>")


def generate_digest(
    report: DigestReport, total_processed: int, source_emails: list[Email]
) -> DigestOutput:
    """Render the report into an HTML digest."""
    citations = []
    for idx in report.source_indices:
        if 1 <= idx <= len(source_emails):
            citations.append(_mla_citation(idx, source_emails[idx - 1]))

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    env.globals["render_section"] = _render_section
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

    edition = "AM" if digest.generated_at.hour < 16 else "PM"
    html = template.render(digest=digest, citations=citations, edition=edition)

    return DigestOutput(
        generated_at=digest.generated_at,
        total_processed=digest.total_processed,
        report=digest.report,
        source_emails=digest.source_emails,
        html=html,
    )
