"""Microsoft Graph authentication using client credentials flow (app-only).

Uses direct httpx POST to the Azure AD OAuth2 token endpoint.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from email_ingester.config import Config

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def get_graph_token(config: Config) -> str:
    """Acquire an access token for Microsoft Graph using client credentials.

    Raises:
        ConnectionError: Network failure or timeout.
        PermissionError: Bad credentials (400/401).
        RuntimeError: Any other non-200 response.
    """
    url = _TOKEN_URL.format(tenant=config.azure_tenant_id)
    payload = {
        "grant_type": "client_credentials",
        "client_id": config.azure_client_id,
        "client_secret": config.azure_client_secret,
        "scope": _GRAPH_SCOPE,
    }

    try:
        response = httpx.post(url, data=payload, timeout=30)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        msg = f"Network error acquiring Graph token: {exc}"
        raise ConnectionError(msg) from exc
    except httpx.HTTPError as exc:
        msg = f"HTTP error acquiring Graph token: {exc}"
        raise ConnectionError(msg) from exc

    if response.status_code in (400, 401):
        content_type = response.headers.get("content-type", "")
        data = response.json() if content_type.startswith("application/json") else {}
        error_desc = data.get("error_description", response.text)
        msg = f"Authentication failed ({response.status_code}): {error_desc}"
        raise PermissionError(msg)

    if response.status_code != 200:
        msg = f"Token request failed ({response.status_code}): {response.text}"
        raise RuntimeError(msg)

    data = response.json()
    token = data["access_token"]

    # Log token expiry
    expires_in = int(data.get("expires_in", 0))
    if expires_in:
        expiry = datetime.now(tz=UTC) + timedelta(seconds=expires_in)
        logger.info("Graph token acquired, expires at %s (in %ds)", expiry.isoformat(), expires_in)
    else:
        logger.info("Graph token acquired (expiry unknown)")

    return token
