"""Entry point for the email ingester pipeline.

Usage: python -m email_ingester.main

Flow: fetch unread -> process -> summarize -> render -> send -> mark as read
"""

from __future__ import annotations

import logging
import sys

from email_ingester.article_fetcher import fetch_articles
from email_ingester.auth import get_graph_token
from email_ingester.config import Config
from email_ingester.digest import generate_digest
from email_ingester.ingester import fetch_unread_emails, mark_as_read
from email_ingester.processor import process_email
from email_ingester.sender import send_digest
from email_ingester.summarizer import create_client, generate_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Run the full email digest pipeline."""
    logger.info("Loading configuration")
    config = Config.from_env()

    logger.info("Authenticating to Microsoft Graph")
    token = get_graph_token(config)

    logger.info("Fetching unread emails from folder: %s", config.mailbox_folder)
    raw_emails = fetch_unread_emails(config, token)
    logger.info("Found %d unread emails", len(raw_emails))

    if not raw_emails:
        logger.info("No unread emails, nothing to do")
        return

    logger.info("Processing %d emails", len(raw_emails))
    processed = [process_email(e) for e in raw_emails]

    logger.info("Fetching article content from links")
    articles = fetch_articles(processed)
    logger.info("Fetched %d articles", len(articles))

    logger.info("Generating report via LLM")
    client = create_client(config)
    report = generate_report(config, client, processed, articles)

    logger.info("Rendering digest")
    digest = generate_digest(
        report,
        total_processed=len(processed),
        source_emails=processed,
    )

    try:
        logger.info("Sending digest")
        send_digest(config, token, digest)
    except Exception:
        logger.exception("Failed to send digest")

    try:
        mark_as_read(config, token, processed)
    except Exception:
        logger.exception("Failed to mark emails as read")

    logger.info("Pipeline complete: %d emails digested", len(processed))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
