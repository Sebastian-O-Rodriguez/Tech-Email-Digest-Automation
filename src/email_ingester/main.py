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

_MAX_DIGEST_EMAILS = 50


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

    logger.info("Processing %d emails", len(raw_emails))
    all_processed = [process_email(e) for e in raw_emails]

    # Only digest the most recent _MAX_DIGEST_EMAILS.
    # State is saved for ALL fetched emails so they won't be re-fetched.
    digest_batch = all_processed[:_MAX_DIGEST_EMAILS]
    logger.info(
        "Generating digest from %d emails (of %d total fetched)",
        len(digest_batch),
        len(all_processed),
    )

    client = create_client(config)
    report = generate_report(config, client, digest_batch)
    digest = generate_digest(
        report,
        total_processed=len(digest_batch),
        source_emails=digest_batch,
    )

    try:
        logger.info("Sending digest")
        send_digest(config, token, digest)
    except Exception:
        logger.exception("Failed to send digest")

    try:
        mark_as_read(config, token, all_processed)
    except Exception:
        logger.exception("Failed to mark emails as read")

    save_state(state_path, new_state)
    logger.info(
        "Pipeline complete: digested %d, total processed %d", len(digest_batch), len(all_processed)
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
