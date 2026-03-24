"""Entry point for the email ingester pipeline.

Usage: python -m email_ingester.main
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import anthropic

from email_ingester.auth import get_graph_token
from email_ingester.config import Config
from email_ingester.digest import generate_digest
from email_ingester.ingester import fetch_new_emails
from email_ingester.processor import process_email
from email_ingester.scorer import score_and_rank
from email_ingester.sender import send_digest
from email_ingester.state import load_state, save_state
from email_ingester.summarizer import summarize_batch

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
        logger.info("No new emails — skipping digest generation")
        save_state(state_path, new_state)
        return

    # 5. Process (normalize + extract links)
    logger.info("Processing emails")
    processed_emails = [process_email(e) for e in raw_emails]

    # 6. Summarize via LLM
    logger.info("Summarizing %d emails via LLM", len(processed_emails))
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    summarized = summarize_batch(config, client, processed_emails)

    # 7. Score and rank
    logger.info("Scoring and ranking")
    ranked = score_and_rank(summarized)

    # 8. Generate digest
    logger.info("Generating digest")
    digest = generate_digest(ranked)
    logger.info(
        "Digest: %d high, %d medium, %d low",
        len(digest.high_priority),
        len(digest.medium_priority),
        digest.low_priority_count,
    )

    # 9. Send digest — failure should not prevent state save
    try:
        logger.info("Sending digest to %s", config.digest_recipient)
        send_digest(config, token, digest)
    except Exception:
        logger.exception("Failed to send digest — state will still be saved")

    # 10. Save state (always, even on send failure)
    save_state(state_path, new_state)

    logger.info("Pipeline complete")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
