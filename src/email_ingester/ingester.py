"""Fetch emails from Microsoft Graph API with delta query support."""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

from email_ingester.models import Email, State

if TYPE_CHECKING:
    from email_ingester.config import Config

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

logger = logging.getLogger(__name__)


class GraphAuthError(Exception):
    """Raised when the Graph API returns 401 (token expired or invalid)."""


class GraphPermissionError(Exception):
    """Raised when the Graph API returns 403 (insufficient permissions)."""


class GraphThrottleError(Exception):
    """Raised when the Graph API returns 429 (rate limited).

    Check ``retry_after`` (seconds) before retrying.
    """

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
            msg = (
                "Graph API authentication failed (401): "
                f"token may be expired or invalid. Body: {body}"
            )
            raise GraphAuthError(msg)
        case 403:
            raise GraphPermissionError(
                f"Graph API permission denied (403): the application lacks the required "
                f"Mail.Read permission or consent has not been granted. Body: {body}"
            )
        case 429:
            retry_after_raw = response.headers.get("Retry-After")
            retry_after: int | None = None
            if retry_after_raw is not None:
                with contextlib.suppress(ValueError):
                    retry_after = int(retry_after_raw)
            hint = f" Retry after {retry_after}s." if retry_after is not None else ""
            raise GraphThrottleError(
                f"Graph API rate limit exceeded (429).{hint} Body: {body}",
                retry_after=retry_after,
            )
        case _:
            raise GraphAPIError(
                f"Graph API returned unexpected status {status}.",
                status_code=status,
                body=body,
            )


def _parse_email(msg: dict) -> Email | None:
    """Parse a Graph API message object into an Email dataclass.

    Returns None and logs a warning when the message is malformed or missing
    required fields (id, receivedDateTime).
    """
    msg_id = msg.get("id")
    if not msg_id:
        logger.warning("Skipping message with missing 'id' field: %s", msg)
        return None

    received_raw = msg.get("receivedDateTime")
    if not received_raw:
        logger.warning("Skipping message id=%r — missing 'receivedDateTime'.", msg_id)
        return None

    try:
        timestamp = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        logger.warning(
            "Skipping message id=%r — could not parse 'receivedDateTime' %r: %s",
            msg_id,
            received_raw,
            exc,
        )
        return None

    sender_data = msg.get("from", {}).get("emailAddress", {})
    body = msg.get("body", {})

    return Email(
        id=msg_id,
        subject=msg.get("subject") or "(no subject)",
        sender=sender_data.get("address") or "unknown",
        timestamp=timestamp,
        body_text="",  # Populated by processor
        body_html=body.get("content", "") if isinstance(body, dict) else "",
        links=[],  # Populated by processor
    )


def fetch_new_emails(config: Config, token: str, state: State) -> tuple[list[Email], State]:
    """Fetch new/changed emails using delta query. Returns emails and updated state.

    Handles:
    - Empty folder: returns empty list without error
    - Pagination: follows @odata.nextLink until exhausted
    - Malformed messages: skipped with a warning log
    - Deleted-message tombstones: silently skipped
    - API errors: 401/403/429 raise descriptive exceptions; others raise GraphAPIError
    """
    headers = {"Authorization": f"Bearer {token}"}

    if state.delta_token:
        url: str | None = state.delta_token
        logger.info("Resuming delta query from stored delta token.")
    else:
        folder = config.mailbox_folder
        url = (
            f"{_GRAPH_BASE}/users/{config.mailbox_user_id}"
            f"/mailFolders/{folder}/messages/delta"
            f"?$select=id,subject,from,receivedDateTime,body"
            f"&$top=50"
        )
        logger.info("No delta token found — starting full delta sync for folder %r.", folder)

    emails: list[Email] = []
    new_delta_token: str | None = state.delta_token
    page_number = 0

    while url:
        page_number += 1
        logger.info("Fetching page %d from Graph API...", page_number)

        response = httpx.get(url, headers=headers, timeout=30.0)

        if not response.is_success:
            _raise_for_graph_error(response)

        data = response.json()
        messages = data.get("value", [])
        logger.info("Page %d: received %d message(s).", page_number, len(messages))

        for msg in messages:
            msg_id = msg.get("id", "")

            # Delta queries return tombstone objects for deleted messages —
            # they carry @removed but no usable fields; skip them silently.
            if "@removed" in msg:
                logger.debug("Skipping deleted/tombstone message id=%r.", msg_id)
                continue

            if msg_id and msg_id in state.processed_ids:
                logger.debug("Skipping already-processed message id=%r.", msg_id)
                continue

            parsed = _parse_email(msg)
            if parsed is None:
                # Warning already emitted inside _parse_email.
                continue

            emails.append(parsed)

        next_link: str | None = data.get("@odata.nextLink")
        delta_link: str | None = data.get("@odata.deltaLink")

        if delta_link:
            new_delta_token = delta_link
            logger.debug("Delta link captured — pagination complete.")

        if next_link:
            logger.info("Pagination: fetching next page.")

        url = next_link

    logger.info(
        "Fetch complete. %d new message(s) retrieved across %d page(s).",
        len(emails),
        page_number,
    )

    new_processed_ids = state.processed_ids | {e.id for e in emails}
    new_state = State(
        delta_token=new_delta_token,
        processed_ids=new_processed_ids,
        last_run=datetime.now(UTC).isoformat(),
    )

    return emails, new_state
