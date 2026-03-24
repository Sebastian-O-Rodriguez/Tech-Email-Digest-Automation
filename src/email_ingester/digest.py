"""Generate HTML digest from processed emails using Jinja2."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from email_ingester.models import DigestOutput, ProcessedEmail

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_digest(processed_emails: list[ProcessedEmail]) -> DigestOutput:
    """Build a DigestOutput from scored, ranked emails."""
    high = [e for e in processed_emails if e.priority == "high"]
    medium = [e for e in processed_emails if e.priority == "medium"]
    low_count = sum(1 for e in processed_emails if e.priority == "low")

    # Render HTML before constructing frozen dataclass
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("digest.html.j2")

    digest = DigestOutput(
        generated_at=datetime.now(UTC),
        total_processed=len(processed_emails),
        high_priority=high,
        medium_priority=medium,
        low_priority_count=low_count,
    )

    html = template.render(digest=digest)

    return DigestOutput(
        generated_at=digest.generated_at,
        total_processed=digest.total_processed,
        high_priority=digest.high_priority,
        medium_priority=digest.medium_priority,
        low_priority_count=digest.low_priority_count,
        html=html,
    )
