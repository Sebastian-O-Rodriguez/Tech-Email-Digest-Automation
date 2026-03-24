"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """All configuration for the email ingester pipeline."""

    # Azure AD / Microsoft Graph
    azure_tenant_id: str
    azure_client_id: str
    azure_client_secret: str
    mailbox_user_id: str
    mailbox_folder: str

    # LLM (OpenRouter)
    openrouter_api_key: str
    llm_model: str

    # Digest
    digest_recipient: str

    # State
    state_file: str

    @classmethod
    def from_env(cls) -> Config:
        """Load configuration from environment variables. Raises if required vars are missing."""

        def require(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                msg = f"Missing required environment variable: {name}"
                raise OSError(msg)
            return value

        mailbox_user_id = require("MAILBOX_USER")

        return cls(
            azure_tenant_id=require("AZURE_TENANT_ID"),
            azure_client_id=require("AZURE_CLIENT_ID"),
            azure_client_secret=require("AZURE_CLIENT_SECRET"),
            mailbox_user_id=mailbox_user_id,
            mailbox_folder=os.environ.get("TARGET_FOLDER_NAME", "Inbox"),
            openrouter_api_key=require("OPENROUTER_API_KEY"),
            llm_model=os.environ.get("LLM_MODEL", "anthropic/claude-sonnet-4"),
            digest_recipient=os.environ.get("DIGEST_RECIPIENT", mailbox_user_id),
            state_file=os.environ.get("STATE_FILE", "state.json"),
        )
