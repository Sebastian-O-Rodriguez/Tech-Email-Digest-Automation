"""Fetch unread emails from Microsoft Graph API."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import httpx

from email_ingester.models import Email

if TYPE_CHECKING:
    from email_ingester.config import Config

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

logger = logging.getLogger(__name__)


class GraphAuthError(Exception):
    """Raised when the Graph API returns 401."""


class GraphPermissionError(Exception):
    """Raised when the Graph API returns 403."""


class GraphThrottleError(Exception):
    """Raised when the Graph API returns 429."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class GraphAPIError(Exception):
    """Raised for unexpected HTTP errors from the Graph API."""

    def __init__(self, message: str, status_code: int, body: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _raise_for_graph_error(response: httpx.Response) -> None:
    """Inspect a non-2xx response and raise the appropriate exception."""
    status = response.status_code
    body = response.text

    match status:
        case 401:
            raise GraphAuthError(
                f"Graph API authentication failed (401): "
                f"token may be expired or invalid. Body: {body}"
            )
        case 403:
            raise GraphPermissionError(f"Graph API permission denied (403). Body: {body}")
        case 429:
            retry_after_raw = response.headers.get("Retry-After")
            retry_after: int | None = None
            if retry_after_raw is not None:
                with contextlib.suppress(ValueError):
                    retry_after = int(retry_after_raw)
            raise GraphThrottleError(
                f"Graph API rate limit exceeded (429). Body: {body}",
                retry_after=retry_after,
            )
        case _:
            raise GraphAPIError(
                f"Graph API returned unexpected status {status}.",
                status_code=status,
                body=body,
            )


_WELL_KNOWN_FOLDERS = frozenset(
    {"inbox", "drafts", "sentitems", "deleteditems", "junkemail", "archive", "outbox"}
)


def _resolve_folder_id(user_id: str, folder_name: str, headers: dict[str, str]) -> str:
    """Resolve a folder display name to its Graph API folder ID."""
    if folder_name.lower() in _WELL_KNOWN_FOLDERS:
        return folder_name

    url = (
        f"{_GRAPH_BASE}/users/{user_id}/mailFolders"
        f"?$filter=displayName eq '{folder_name}'"
        f"&$select=id,displayName"
    )
    response = httpx.get(url, headers=headers, timeout=30.0)

    if not response.is_success:
        _raise_for_graph_error(response)

    folders = response.json().get("value", [])
    if not folders:
        msg = f"Mail folder '{folder_name}' not found for user {user_id}"
        raise GraphAPIError(msg, status_code=404, body="")

    folder_id = folders[0]["id"]
    logger.info("Resolved folder '%s' to ID '%s'.", folder_name, folder_id)
    return folder_id


def _parse_email(msg: dict) -> Email | None:
    """Parse a Graph API message into an Email dataclass."""
    from datetime import datetime

    msg_id = msg.get("id")
    if not msg_id:
        logger.warning("Skipping message with missing 'id' field")
        return None

    received_raw = msg.get("receivedDateTime")
    if not received_raw:
        logger.warning("Skipping message id=%r, missing receivedDateTime", msg_id)
        return None

    try:
        timestamp = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        logger.warning("Skipping message id=%r, bad date %r: %s", msg_id, received_raw, exc)
        return None

    sender_data = msg.get("from", {}).get("emailAddress", {})
    body = msg.get("body", {})

    return Email(
        id=msg_id,
        subject=msg.get("subject") or "(no subject)",
        sender=sender_data.get("address") or "unknown",
        timestamp=timestamp,
        body_text="",
        body_html=body.get("content", "") if isinstance(body, dict) else "",
        links=[],
    )


def fetch_unread_emails(config: Config, token: str) -> list[Email]:
    """Fetch all unread emails from the target folder.

    Uses isRead eq false filter. After processing, the pipeline marks
    them as read, so the next run only picks up new arrivals.
    """
    headers = {"Authorization": f"Bearer {token}"}
    folder_id = _resolve_folder_id(config.mailbox_user_id, config.mailbox_folder, headers)

    url: str | None = (
        f"{_GRAPH_BASE}/users/{config.mailbox_user_id}"
        f"/mailFolders/{folder_id}/messages"
        f"?$filter=isRead eq false"
        f"&$select=id,subject,from,receivedDateTime,body"
        f"&$top=200"
        f"&$orderby=receivedDateTime desc"
    )

    emails: list[Email] = []
    page_number = 0

    while url:
        page_number += 1
        logger.info("Fetching unread page %d...", page_number)

        response = httpx.get(url, headers=headers, timeout=60.0)
        if not response.is_success:
            _raise_for_graph_error(response)

        data = response.json()
        messages = data.get("value", [])
        logger.info("Page %d: %d unread message(s).", page_number, len(messages))

        for msg in messages:
            parsed = _parse_email(msg)
            if parsed is not None:
                emails.append(parsed)

        url = data.get("@odata.nextLink")

    logger.info("Fetch complete: %d unread email(s).", len(emails))
    return emails


def mark_as_read(config: Config, token: str, emails: list[Email]) -> None:
    """Mark emails as read via Graph API PATCH. Best-effort, never raises."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    succeeded = 0
    for email in emails:
        url = f"{_GRAPH_BASE}/users/{config.mailbox_user_id}/messages/{email.id}"
        try:
            response = httpx.patch(url, headers=headers, json={"isRead": True}, timeout=10.0)
            if response.is_success:
                succeeded += 1
            else:
                logger.warning("Failed to mark %s as read: %d", email.id, response.status_code)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning("Network error marking %s as read: %s", email.id, exc)
    logger.info("Marked %d/%d emails as read", succeeded, len(emails))
