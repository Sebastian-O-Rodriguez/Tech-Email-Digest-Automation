"""Generate HTML digest from the aggregated report using Jinja2."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader

from email_ingester.models import DigestOutput, DigestReport, Email

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _outlook_url(message_id: str) -> str:
    """Build an Outlook Web deep link for a message ID."""
    encoded = quote(message_id, safe="")
    return f"https://outlook.office365.com/mail/id/{encoded}"


def generate_digest(
    report: DigestReport, total_processed: int, source_emails: list[Email]
) -> DigestOutput:
    """Render the report into an HTML digest."""
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    env.globals["outlook_url"] = _outlook_url
    template = env.get_template("digest.html.j2")

    digest = DigestOutput(
        generated_at=datetime.now(UTC),
        total_processed=total_processed,
        report=report,
        source_emails=source_emails,
    )

    html = template.render(digest=digest)

    return DigestOutput(
        generated_at=digest.generated_at,
        total_processed=digest.total_processed,
        report=digest.report,
        source_emails=digest.source_emails,
        html=html,
    )
