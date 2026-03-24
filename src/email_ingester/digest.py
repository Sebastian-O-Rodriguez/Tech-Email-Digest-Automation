"""Generate HTML digest from the aggregated report using Jinja2."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from email_ingester.models import DigestOutput, DigestReport

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_digest(report: DigestReport, total_processed: int) -> DigestOutput:
    """Render the report into an HTML digest."""
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("digest.html.j2")

    digest = DigestOutput(
        generated_at=datetime.now(UTC),
        total_processed=total_processed,
        report=report,
    )

    html = template.render(digest=digest)

    return DigestOutput(
        generated_at=digest.generated_at,
        total_processed=digest.total_processed,
        report=digest.report,
        html=html,
    )
