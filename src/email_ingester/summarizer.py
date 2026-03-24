"""Aggregate email summarization via OpenRouter (OpenAI-compatible API).

Data flow: list[Email] -> generate_report() -> DigestReport
Single LLM call that reads all emails and produces one aggregated brief.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import openai

from email_ingester.models import DigestReport, Email  # noqa: TC001

if TYPE_CHECKING:
    from email_ingester.config import Config

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_SYSTEM_PROMPT = """\
You are an intelligence analyst for Guava AI, a software company. You produce \
a concise daily brief from a batch of newsletter emails. Your reader is a \
technical leader who needs to stay current on backend, frontend, design, dev \
tooling, B2B software, and AI/ML.

The emails below are numbered [1], [2], etc. Read them all and produce ONE \
aggregated JSON report. Do not summarize each email individually. Synthesize \
and group the information.

Respond with ONLY valid JSON in this exact format:
{
  "breaking_news": "Dense notes with source refs like [1] [3]",
  "tech_stacks": "Dense notes with source refs like [2] [5]",
  "new_software": "Dense notes with source refs",
  "deep_dives": "Dense notes with source refs",
  "sources": [1, 3, 5, 12]
}

Rules:
- Total report must be under 1500 characters.
- Write in dense, telegraphic style. No full sentences. Use semicolons to \
separate items within a section. Pack maximum information per character.
- After each claim, put the source email number in brackets. These numbers \
match the input email numbers [1], [2], etc. The reader can click these to \
open the original email.
- Example: "Deno 2.1 drops Node compat layer [4]; Bun adds S3 native \
client [7]; Cloudflare Workers now supports Python 3.12 [12]."
- Never use em dashes.
- Never start items with "Notable:" or "Key:" or similar labels.
- sources: list ALL input email numbers you referenced in the report.
- If a section has nothing, write "Nothing notable this cycle."
"""


def _fallback_report(reason: str) -> DigestReport:
    """Return a safe fallback report when the LLM call fails."""
    logger.warning("Using fallback report: %s", reason)
    return DigestReport(
        breaking_news="Report generation failed. Check logs for details.",
        tech_stacks="",
        new_software="",
        deep_dives="",
    )


def create_client(config: Config) -> openai.OpenAI:
    """Create an OpenAI client configured for OpenRouter."""
    return openai.OpenAI(
        base_url=_OPENROUTER_BASE_URL,
        api_key=config.openrouter_api_key,
    )


def _format_emails_for_llm(emails: list[Email]) -> str:
    """Format all emails into a condensed feed for the LLM.

    Each email is trimmed to subject, sender, and first 300 chars of body
    plus up to 5 links. This keeps the total prompt manageable even for
    50+ emails.
    """
    parts = []
    for i, email in enumerate(emails, 1):
        links_str = " | ".join(email.links[:5]) if email.links else "(none)"
        body_preview = email.body_text[:300].replace("\n", " ").strip()
        parts.append(
            f"[{i}] {email.subject}\nFrom: {email.sender}\n{body_preview}\nLinks: {links_str}"
        )
    return "\n\n".join(parts)


def generate_report(config: Config, client: openai.OpenAI, emails: list[Email]) -> DigestReport:
    """Send all emails to the LLM in one call and get an aggregated report back."""
    user_content = _format_emails_for_llm(emails)
    logger.info("LLM prompt size: %d chars for %d emails", len(user_content), len(emails))

    try:
        response = client.chat.completions.create(
            model=config.llm_model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
    except openai.APIError as exc:
        logger.error("OpenRouter API error generating report: %s", exc)
        return _fallback_report(reason="api_error")

    if not response.choices:
        logger.error("LLM returned no choices")
        return _fallback_report(reason="empty_choices")

    raw = response.choices[0].message.content
    logger.info("LLM response length: %d chars", len(raw) if raw else 0)

    if not raw or not raw.strip():
        logger.error("LLM returned blank response")
        return _fallback_report(reason="blank_response")

    # Strip markdown code fences if present (```json ... ```)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse error: %s -- raw: %.300s", exc, raw)
        return _fallback_report(reason="json_parse_error")

    source_indices = []
    for idx in data.get("sources", []):
        if isinstance(idx, int):
            source_indices.append(idx)

    return DigestReport(
        breaking_news=data.get("breaking_news", ""),
        tech_stacks=data.get("tech_stacks", ""),
        new_software=data.get("new_software", ""),
        deep_dives=data.get("deep_dives", ""),
        source_indices=source_indices,
    )
