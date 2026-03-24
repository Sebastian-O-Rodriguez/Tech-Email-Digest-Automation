"""Generate HTML digest from processed emails using Jinja2."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from email_ingester.models import DigestOutput, ProcessedEmail

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_digest(processed_emails: list[ProcessedEmail]) -> DigestOutput:
    """Build a DigestOutput from scored, ranked emails grouped by topic."""
    breaking = [e for e in processed_emails if e.topic == "breaking_news"]
    stacks = [e for e in processed_emails if e.topic == "tech_stacks"]
    software = [e for e in processed_emails if e.topic == "new_software"]
    dives = [e for e in processed_emails if e.topic == "deep_dives"]

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("digest.html.j2")

    digest = DigestOutput(
        generated_at=datetime.now(UTC),
        total_processed=len(processed_emails),
        breaking_news=breaking,
        tech_stacks=stacks,
        new_software=software,
        deep_dives=dives,
    )

    html = template.render(digest=digest)

    return DigestOutput(
        generated_at=digest.generated_at,
        total_processed=digest.total_processed,
        breaking_news=digest.breaking_news,
        tech_stacks=digest.tech_stacks,
        new_software=digest.new_software,
        deep_dives=digest.deep_dives,
        html=html,
    )
