"""LLM-based email summarization via OpenRouter (OpenAI-compatible API).

Data flow: Email → summarize_email() → EmailSummary
The scorer then combines EmailSummary + Email → ProcessedEmail.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import openai

from email_ingester.models import Email, EmailSummary  # noqa: TC001

if TYPE_CHECKING:
    from email_ingester.config import Config

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_VALID_TOPICS = frozenset({"breaking_news", "tech_stacks", "new_software", "deep_dives"})

_SYSTEM_PROMPT = """\
You are an email analysis assistant. Given an email, produce a structured JSON summary.

Respond with ONLY valid JSON in this exact format:
{
  "summary": "One-line summary, max 75 characters",
  "topic": "breaking_news|tech_stacks|new_software|deep_dives",
  "key_links": ["most useful URLs from the email, max 3"]
}

Topic guidelines:
- breaking_news: urgent updates, security alerts, outages, major announcements
- tech_stacks: frameworks, languages, infrastructure, architecture trends
- new_software: tools, apps, product launches, version releases
- deep_dives: tutorials, in-depth articles, analyses, long-form content

Keep the summary punchy — one sentence, max 75 characters. No filler words.
"""


def _fallback_summary(email_id: str, reason: str) -> EmailSummary:
    """Return a safe fallback EmailSummary when LLM processing fails."""
    return EmailSummary(
        email_id=email_id,
        summary="(summarization failed)",
        topic="deep_dives",
        key_links=[],
        model_confidence=0.0,
    )


def create_client(config: Config) -> openai.OpenAI:
    """Create an OpenAI client configured for OpenRouter."""
    return openai.OpenAI(
        base_url=_OPENROUTER_BASE_URL,
        api_key=config.openrouter_api_key,
    )


def summarize_email(config: Config, client: openai.OpenAI, email: Email) -> EmailSummary:
    """Summarize a single email using the LLM via OpenRouter.

    Returns an EmailSummary (intermediate type). The scorer combines this
    with the original Email to produce a final ProcessedEmail.

    On LLM API errors or JSON parse failures, logs the error and returns a
    fallback EmailSummary with topic="deep_dives".
    """
    user_content = f"""Subject: {email.subject}
From: {email.sender}
Date: {email.timestamp.isoformat()}

Body:
{email.body_text[:3000]}

Links found:
{chr(10).join(email.links[:20]) if email.links else "(none)"}"""

    try:
        response = client.chat.completions.create(
            model=config.llm_model,
            max_tokens=256,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
    except openai.APIError as exc:
        logger.error(
            "OpenRouter API error while summarizing email %s: %s",
            email.id,
            exc,
        )
        return _fallback_summary(email.id, reason="api_error")

    if not response.choices:
        logger.warning(
            "Empty choices in LLM response for email %s; using fallback summary.",
            email.id,
        )
        return _fallback_summary(email.id, reason="empty_content")

    raw = response.choices[0].message.content

    if not raw or not raw.strip():
        logger.warning(
            "Blank text in LLM response for email %s; using fallback summary.",
            email.id,
        )
        return _fallback_summary(email.id, reason="blank_text")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "JSON parse error for email %s: %s — raw response: %.200s",
            email.id,
            exc,
            raw,
        )
        return _fallback_summary(email.id, reason="json_parse_error")

    topic = data.get("topic", "deep_dives")
    if topic not in _VALID_TOPICS:
        logger.warning("Unknown topic %r for email %s, defaulting to deep_dives", topic, email.id)
        topic = "deep_dives"

    return EmailSummary(
        email_id=email.id,
        summary=data.get("summary", "")[:75],
        topic=topic,
        key_links=data.get("key_links", []),
        model_confidence=0.5,
    )


def summarize_batch(
    config: Config, client: openai.OpenAI, emails: list[Email]
) -> list[tuple[Email, EmailSummary]]:
    """Summarize a batch of emails sequentially.

    Returns (Email, EmailSummary) pairs so the scorer has both available.
    A failure on a single email is logged and skipped — the batch continues.
    """
    results: list[tuple[Email, EmailSummary]] = []
    for email in emails:
        try:
            summary = summarize_email(config, client, email)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Unexpected error summarizing email %s; skipping. Error: %s",
                email.id,
                exc,
            )
            summary = _fallback_summary(email.id, reason="unexpected_error")
        results.append((email, summary))
    return results
