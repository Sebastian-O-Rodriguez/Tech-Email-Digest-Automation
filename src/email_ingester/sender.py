"""Send digest email via Microsoft Graph API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from email_ingester.config import Config
    from email_ingester.models import DigestOutput

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

logger = logging.getLogger(__name__)


class SendError(Exception):
    """Raised when the digest email cannot be sent."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def send_digest(config: Config, token: str, digest: DigestOutput) -> None:
    """Send the digest as an HTML email via Graph API.

    Raises:
        SendError: On auth failure, rate limit, or other API/network error.
    """
    url = f"{_GRAPH_BASE}/users/{config.mailbox_user_id}/sendMail"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    timestamp = digest.generated_at.strftime("%B %d, %Y %I:%M %p UTC")
    subject = f"Email Digest — {timestamp}"

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": digest.html,
            },
            "toRecipients": [{"emailAddress": {"address": config.digest_recipient}}],
        },
        "saveToSentItems": False,
    }

    logger.info(
        "Sending digest email to %s (%d chars HTML)",
        config.digest_recipient,
        len(digest.html),
    )

    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=30.0)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        msg = f"Network error sending digest: {exc}"
        raise SendError(msg) from exc
    except httpx.HTTPError as exc:
        msg = f"HTTP error sending digest: {exc}"
        raise SendError(msg) from exc

    if response.is_success:
        logger.info("Digest sent successfully")
        return

    status = response.status_code
    body = response.text

    match status:
        case 401:
            msg = f"Authentication failed sending digest (401): {body}"
        case 403:
            msg = f"Permission denied sending digest (403): {body}"
        case 429:
            msg = f"Rate limited sending digest (429): {body}"
        case _:
            msg = f"Failed to send digest ({status}): {body}"

    raise SendError(msg, status_code=status)
