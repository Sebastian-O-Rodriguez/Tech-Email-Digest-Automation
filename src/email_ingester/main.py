"""Entry point for the email ingester pipeline.

Usage:
  python -m email_ingester              # Full run (prepare + send)
  python -m email_ingester --prepare    # Prepare digest, save to file
  python -m email_ingester --send       # Send prepared digest
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from email_ingester.auth import get_graph_token
from email_ingester.config import Config
from email_ingester.digest import generate_digest
from email_ingester.ingester import fetch_new_emails, fetch_unread_emails, mark_as_read
from email_ingester.processor import process_email
from email_ingester.sender import send_digest
from email_ingester.state import load_state, save_state
from email_ingester.summarizer import create_client, generate_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_BATCH_SIZE = 50
_PREPARED_FILE = Path("prepared_digest.json")


def _prepare(config: Config, token: str, state_path: Path) -> None:
    """Fetch, process, generate report, save digest data to file."""
    state = load_state(state_path)
    logger.info("State loaded: %d previously processed emails", len(state.processed_ids))

    logger.info("Fetching new emails from folder: %s", config.mailbox_folder)
    raw_emails, new_state = fetch_new_emails(config, token, state)
    logger.info("Fetched %d new emails", len(raw_emails))

    if not raw_emails:
        logger.info("Delta returned 0, checking for unread emails (fallback)")
        raw_emails, new_state = fetch_unread_emails(config, token, new_state)
        if not raw_emails:
            logger.info("No unread emails either, skipping digest generation")
            save_state(state_path, new_state)
            return

    logger.info("Processing emails")
    all_processed = [process_email(e) for e in raw_emails]

    client = create_client(config)
    digests_data = []

    for i in range(0, len(all_processed), _BATCH_SIZE):
        batch = all_processed[i : i + _BATCH_SIZE]
        batch_num = i // _BATCH_SIZE + 1
        logger.info(
            "Batch %d: generating report from %d emails (of %d total)",
            batch_num,
            len(batch),
            len(all_processed),
        )
        report = generate_report(config, client, batch)
        digest = generate_digest(report, total_processed=len(batch), source_emails=batch)
        digests_data.append(
            {
                "html": digest.html,
                "generated_at": digest.generated_at.isoformat(),
                "email_ids": [e.id for e in batch],
            }
        )

    prepared = {
        "digests": digests_data,
        "all_email_ids": [e.id for e in all_processed],
    }
    _PREPARED_FILE.write_text(json.dumps(prepared), encoding="utf-8")
    logger.info("Prepared %d digest(s), saved to %s", len(digests_data), _PREPARED_FILE)

    save_state(state_path, new_state)


def _send(config: Config, token: str) -> None:
    """Send prepared digest(s) and mark emails as read."""
    if not _PREPARED_FILE.exists():
        logger.info("No prepared digest found, nothing to send")
        return

    prepared = json.loads(_PREPARED_FILE.read_text(encoding="utf-8"))
    digests = prepared["digests"]
    all_ids = prepared["all_email_ids"]

    from datetime import UTC, datetime

    from email_ingester.models import DigestOutput, DigestReport, Email

    for i, d in enumerate(digests, 1):
        dummy_report = DigestReport(
            breaking_news="", tech_stacks="", new_software="", deep_dives=""
        )
        digest = DigestOutput(
            generated_at=datetime.fromisoformat(d["generated_at"]),
            total_processed=0,
            report=dummy_report,
            html=d["html"],
        )
        try:
            logger.info("Sending digest %d/%d", i, len(digests))
            send_digest(config, token, digest)
        except Exception:
            logger.exception("Failed to send digest %d", i)

    # Mark all as read using minimal Email objects
    emails_to_mark = [
        Email(
            id=eid, subject="", sender="", timestamp=datetime.now(UTC), body_text="", body_html=""
        )
        for eid in all_ids
    ]
    try:
        mark_as_read(config, token, emails_to_mark)
    except Exception:
        logger.exception("Failed to mark emails as read")

    _PREPARED_FILE.unlink(missing_ok=True)
    logger.info("Send complete")


def main() -> None:
    """Run the full email digest pipeline."""
    config = Config.from_env()
    token = get_graph_token(config)
    state_path = Path(config.state_file)

    mode = sys.argv[1] if len(sys.argv) > 1 else None

    if mode == "--prepare":
        logger.info("Mode: prepare only")
        _prepare(config, token, state_path)
    elif mode == "--send":
        logger.info("Mode: send only")
        _send(config, token)
    else:
        logger.info("Mode: full run")
        _prepare(config, token, state_path)
        _send(config, token)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
