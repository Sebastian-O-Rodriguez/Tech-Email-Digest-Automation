"""One-off admin script: mark the backlogged messages as unread.

Run inside GitHub Actions with the same secrets as the digest pipeline.
Not part of the digest pipeline; used to restore the backlogged emails
consumed by the 2026-09-17 fallback run (which marked them read).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mark_unread")

GRAPH = "https://graph.microsoft.com/v1.0"

# Only messages marked read by the 2026-09-17 fallback run (~12:55Z), not the
# full historical read backlog.
CUTOFF = "2026-09-17T12:50:00Z"


def get_token() -> str:
    resp = httpx.post(
        f"https://login.microsoftonline.com/{os.environ['AZURE_TENANT_ID']}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["AZURE_CLIENT_ID"],
            "client_secret": os.environ["AZURE_CLIENT_SECRET"],
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def resolve_folder_id(client: httpx.Client, mailbox: str, name: str) -> str:
    resp = client.get(
        f"{GRAPH}/users/{mailbox}/mailFolders",
        params={"$filter": f"displayName eq '{name}'", "$select": "id"},
    )
    resp.raise_for_status()
    value = resp.json().get("value", [])
    if not value:
        log.error("Folder %r not found", name)
        sys.exit(1)
    return value[0]["id"]


def collect_read_ids(client: httpx.Client, folder_id: str, since: str) -> list[str]:
    """Read messages modified (e.g. marked read) at/after `since`."""
    ids: list[str] = []
    url: str | None = (
        f"{GRAPH}/users/{os.environ['MAILBOX_USER']}/mailFolders/{folder_id}/messages"
    )
    params = {
        "$filter": f"isRead eq true and lastModifiedDateTime ge {since}",
        "$select": "id",
        "$top": "200",
        "$orderby": "lastModifiedDateTime desc",
    }
    while url:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        ids.extend(m["id"] for m in data.get("value", []))
        url = data.get("@odata.nextLink")
        params = None  # nextLink already carries the paging params
    return ids


def mark_unread(client: httpx.Client, mailbox: str, message_id: str) -> bool:
    for attempt in range(6):
        resp = client.patch(
            f"{GRAPH}/users/{mailbox}/messages/{message_id}", json={"isRead": False}
        )
        if resp.status_code < 300:
            return True
        if resp.status_code == 429:
            delay = float(resp.headers.get("Retry-After", 2**attempt))
            log.info("429 throttled, retrying in %.1fs", delay)
            time.sleep(delay)
            continue
        log.warning("PATCH failed (%d) for %s...", resp.status_code, message_id[:25])
        return False
    log.warning("Gave up on %s... after retries", message_id[:25])
    return False


def main() -> None:
    mailbox = os.environ["MAILBOX_USER"]
    folder_name = os.environ.get("TARGET_FOLDER_NAME", "Inbox")
    token = get_token()
    with httpx.Client(
        headers={"Authorization": f"Bearer {token}"}, timeout=60
    ) as client:
        folder_id = resolve_folder_id(client, mailbox, folder_name)
        ids = collect_read_ids(client, folder_id, CUTOFF)
        log.info("Found %d message(s) to flip in folder %r", len(ids), folder_name)

        def work(mid: str) -> bool:
            return mark_unread(client, mailbox, mid)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(work, ids))
        log.info("Marked unread: %d/%d", sum(results), len(ids))
        if sum(results) != len(ids):
            sys.exit(1)


if __name__ == "__main__":
    main()
