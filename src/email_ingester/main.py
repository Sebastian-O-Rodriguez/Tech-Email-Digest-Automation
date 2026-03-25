"""Entry point for the email ingester pipeline.

Usage: python -m email_ingester.main
"""

from __future__ import annotations

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


def main() -> None:
    """Run the full email digest pipeline."""
    logger.info("Loading configuration")
    config = Config.from_env()

    logger.info("Authenticating to Microsoft Graph")
    token = get_graph_token(config)

    state_path = Path(config.state_file)
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
    batch_count = 0

    for i in range(0, len(all_processed), _BATCH_SIZE):
        batch = all_processed[i : i + _BATCH_SIZE]
        batch_count += 1
        logger.info(
            "Batch %d: generating report from %d emails (of %d total)",
            batch_count,
            len(batch),
            len(all_processed),
        )

        report = generate_report(config, client, batch)
        digest = generate_digest(
            report,
            total_processed=len(batch),
            source_emails=batch,
        )

        try:
            logger.info("Batch %d: sending digest", batch_count)
            send_digest(config, token, digest)
        except Exception:
            logger.exception("Batch %d: failed to send digest", batch_count)

    try:
        mark_as_read(config, token, all_processed)
    except Exception:
        logger.exception("Failed to mark emails as read")

    save_state(state_path, new_state)
    logger.info("Pipeline complete: %d batches, %d emails", batch_count, len(all_processed))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
