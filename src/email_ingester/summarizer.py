"""Aggregate email summarization via OpenRouter (OpenAI-compatible API).

Data flow: list[Email] -> generate_report() -> DigestReport
Single LLM call that reads all emails and produces one aggregated brief.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import openai

from email_ingester.models import DigestReport, Email, Footnote  # noqa: TC001

if TYPE_CHECKING:
    from email_ingester.config import Config

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_SYSTEM_PROMPT = """\
You are an intelligence analyst for Guava AI, a software company. You produce \
a concise daily brief from a batch of newsletter emails. Your reader is a \
technical leader who needs to stay current on backend, frontend, design, dev \
tooling, B2B software, and AI/ML.

Read all the emails below and produce ONE aggregated JSON report. Do not \
summarize each email individually. Synthesize and group the information.

Respond with ONLY valid JSON in this exact format:
{
  "breaking_news": "Dense bullet-style notes on urgent developments, outages, \
security alerts, major announcements. Pack in specifics: names, versions, \
dates. If nothing qualifies, write 'Nothing breaking this cycle.'",
  "tech_stacks": "Dense bullet-style notes on backend, frontend, infra, \
architecture, framework trends. Include specific tech names and what changed.",
  "new_software": "Dense bullet-style notes on new tools, product launches, \
version releases, dev tooling. Name the product, what it does, why it matters.",
  "deep_dives": "Dense bullet-style notes on notable long-form content, \
tutorials, analyses. Name the topic and source.",
  "footnotes": [
    {"title": "Short title", "url": "https://..."},
    {"title": "Short title", "url": "https://..."}
  ]
}

Rules:
- Total report must be under 1500 characters (excluding footnotes).
- Write in dense, telegraphic style. No full sentences. Use semicolons to \
separate items within a section. Pack maximum information per character.
- Example style: "Deno 2.1 drops Node compat layer; Bun adds S3 native \
client; Cloudflare Workers now supports Python 3.12 runtime."
- Never use em dashes.
- Never start items with "Notable:" or "Key:" or similar labels.
- Footnotes: 5-10 most important links. Short titles.
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
        footnotes=[],
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

    footnotes = []
    for i, fn in enumerate(data.get("footnotes", []), 1):
        if isinstance(fn, dict) and fn.get("title") and fn.get("url"):
            footnotes.append(Footnote(index=i, title=fn["title"], url=fn["url"]))

    return DigestReport(
        breaking_news=data.get("breaking_news", ""),
        tech_stacks=data.get("tech_stacks", ""),
        new_software=data.get("new_software", ""),
        deep_dives=data.get("deep_dives", ""),
        footnotes=footnotes,
    )
