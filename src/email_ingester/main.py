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
from email_ingester.ingester import fetch_new_emails, mark_as_read
from email_ingester.processor import process_email
from email_ingester.sender import send_digest
from email_ingester.state import load_state, save_state
from email_ingester.summarizer import create_client, generate_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Run the full email digest pipeline."""
    # 1. Load config
    logger.info("Loading configuration")
    config = Config.from_env()

    # 2. Authenticate
    logger.info("Authenticating to Microsoft Graph")
    token = get_graph_token(config)

    # 3. Restore state
    state_path = Path(config.state_file)
    state = load_state(state_path)
    logger.info(
        "State loaded: %d previously processed emails",
        len(state.processed_ids),
    )

    # 4. Fetch new emails
    logger.info("Fetching new emails from folder: %s", config.mailbox_folder)
    raw_emails, new_state = fetch_new_emails(config, token, state)
    logger.info("Fetched %d new emails", len(raw_emails))

    if not raw_emails:
        logger.info("No new emails, skipping digest generation")
        save_state(state_path, new_state)
        return

    # 5. Process (normalize + extract links)
    logger.info("Processing emails")
    processed_emails = [process_email(e) for e in raw_emails]

    # 6. Generate aggregated report via LLM
    logger.info("Generating report from %d emails via LLM", len(processed_emails))
    client = create_client(config)
    report = generate_report(config, client, processed_emails)

    # 7. Render digest HTML
    logger.info("Rendering digest")
    digest = generate_digest(
        report,
        total_processed=len(processed_emails),
        source_emails=processed_emails,
    )

    # 8. Send digest
    try:
        logger.info("Sending digest to %s", config.digest_recipient)
        send_digest(config, token, digest)
    except Exception:
        logger.exception("Failed to send digest, state will still be saved")

    # 9. Mark digested emails as read
    try:
        mark_as_read(config, token, processed_emails)
    except Exception:
        logger.exception("Failed to mark emails as read")

    # 10. Save state (always)
    save_state(state_path, new_state)

    logger.info("Pipeline complete")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
