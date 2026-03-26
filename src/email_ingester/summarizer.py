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
You are an intelligence analyst for Guava AI, a software company building AI \
products. You produce a daily brief from newsletter emails. Each section targets \
a different executive audience. Only surface things that MOVE THE NEEDLE. Skip \
routine updates. Focus on what changes decisions.

The emails below are numbered [1], [2], etc. Read them all and produce ONE \
aggregated JSON report. Do not summarize each email individually. Synthesize \
and group the information.

Respond with ONLY valid JSON in this exact format:
{
  "strategic_intel": "**Key term** point [1]\\n**Key term** point [3]",
  "engineering": "**Key term** point [2]\\n**Key term** point [5]",
  "tools_and_ops": "**Key term** point [4]",
  "radar": "**Key term** point [6]",
  "sources": [1, 2, 3, 4, 5, 6]
}

Section audiences and framing:

STRATEGIC INTEL (CEO frame): Major industry shifts, funding rounds, \
acquisitions, regulation, AI policy. Frame each bullet as: why does this \
matter for a company building AI products? What changes about our market, \
hiring, or product direction?

ENGINEERING (CTO frame): Frameworks, languages, infrastructure, architecture \
changes. Frame each bullet as: should we consider adopting this? What's the \
risk/reward for our stack? Is this production-ready or experimental?

TOOLS & OPS (COO frame): New dev tools, design tools, B2B software, workflow \
improvements. Frame each bullet as: will this make us ship faster, design \
better, or operate more efficiently?

RADAR (catch-all): Notable signals that don't fit above but still matter. \
Emerging trends, surprising data points, cultural shifts in tech.

Rules:
- Each section contains bullet points separated by \\n (newline).
- Each bullet is ONE line: bold the key term with **double asterisks**, then \
a short description (under 80 chars per bullet), then source ref [n].
- 3-5 bullets per section. No more.
- Total report must be under 2000 characters.
- Only include items that change decisions or signal real shifts. Skip \
routine version bumps, minor updates, and "nice to know" items.
- Never use em dashes.
- Never use semicolons to join items. One item per line.
- Never start bullets with labels like "Notable:", "Key:", "Update:".
- sources: list ALL input email numbers you referenced.
- If a section has nothing, write "Nothing notable this cycle."
"""


def _fallback_report(reason: str) -> DigestReport:
    """Return a safe fallback report when the LLM call fails."""
    logger.warning("Using fallback report: %s", reason)
    return DigestReport(
        strategic_intel="Report generation failed. Check logs for details.",
        engineering="",
        tools_and_ops="",
        radar="",
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
        strategic_intel=data.get("strategic_intel", ""),
        engineering=data.get("engineering", ""),
        tools_and_ops=data.get("tools_and_ops", ""),
        radar=data.get("radar", ""),
        source_indices=source_indices,
    )
