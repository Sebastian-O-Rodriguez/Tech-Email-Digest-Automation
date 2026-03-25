"""Generate HTML digest from the aggregated report using Jinja2."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from email_ingester.models import DigestOutput, DigestReport, Email

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _mla_citation(idx: int, email: Email) -> str:
    """Format an email as an MLA-style citation."""
    date_str = email.timestamp.strftime("%d %b. %Y")
    return f'[{idx}] {email.sender}. "{email.subject}." {date_str}.'


def generate_digest(
    report: DigestReport, total_processed: int, source_emails: list[Email]
) -> DigestOutput:
    """Render the report into an HTML digest.

    source_emails is the full list of processed emails (matching the indices
    the LLM used). Only emails referenced in source_indices appear in the
    citations section.
    """
    # Build MLA citations for referenced emails only
    citations = []
    for idx in report.source_indices:
        if 1 <= idx <= len(source_emails):
            citations.append(_mla_citation(idx, source_emails[idx - 1]))

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
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

    html = template.render(digest=digest, citations=citations)

    return DigestOutput(
        generated_at=digest.generated_at,
        total_processed=digest.total_processed,
        report=digest.report,
        source_emails=digest.source_emails,
        html=html,
    )
