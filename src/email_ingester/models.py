"""Data contracts for the email ingestion pipeline.

All pipeline modules pass data using these dataclasses.
Architect agent owns this file — other agents should not modify it.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Topic = Literal["breaking_news", "tech_stacks", "new_software", "deep_dives"]


@dataclass(frozen=True)
class Email:
    """Raw email fetched from Microsoft Graph."""

    id: str
    subject: str
    sender: str
    timestamp: datetime
    body_text: str
    body_html: str
    links: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EmailSummary:
    """Intermediate output from the LLM summarizer, before scoring.

    The summarizer produces this; the scorer consumes it alongside rule-based
    signals to produce a final ProcessedEmail with a hybrid score.
    """

    email_id: str
    summary: str
    topic: Topic
    key_links: list[str] = field(default_factory=list)
    model_confidence: float = 0.0


@dataclass(frozen=True)
class ProcessedEmail:
    """Email after LLM summarization and scoring."""

    email: Email
    summary: str
    topic: Topic
    key_links: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass(frozen=True)
class DigestOutput:
    """Generated digest ready for sending."""

    generated_at: datetime
    total_processed: int
    breaking_news: list[ProcessedEmail] = field(default_factory=list)
    tech_stacks: list[ProcessedEmail] = field(default_factory=list)
    new_software: list[ProcessedEmail] = field(default_factory=list)
    deep_dives: list[ProcessedEmail] = field(default_factory=list)
    html: str = ""


@dataclass
class State:
    """Persistent state between runs.

    Note: ``processed_ids`` is a set for O(1) lookup during deduplication.
    Sets are not JSON-serializable — the ``state.py`` module handles
    conversion (set <-> sorted list) during load/save. Do not attempt
    to serialize State directly with ``json.dumps``; always go through
    ``state.save_state`` / ``state.load_state``.
    """

    delta_token: str | None = None
    processed_ids: set[str] = field(default_factory=set)
    last_run: str | None = None  # ISO 8601 timestamp
