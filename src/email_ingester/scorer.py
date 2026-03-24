"""Hybrid scoring: combine rule-based signals with LLM priority.

Data flow: (Email, EmailSummary) → score_email() → ProcessedEmail
Rule-based signals come from Email; LLM signals come from EmailSummary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from email_ingester.models import Email, EmailSummary, ProcessedEmail

from email_ingester.models import ProcessedEmail as _ProcessedEmail

logger = logging.getLogger(__name__)

# Priority weights from LLM
_PRIORITY_SCORES = {
    "high": 1.0,
    "medium": 0.5,
    "low": 0.1,
}

# Rule-based score adjustments
_LINK_BONUS = 0.1  # Per useful link (max 3)
_SHORT_SUBJECT_PENALTY = -0.05  # Subject < 10 chars (likely auto-generated)
_LONG_BODY_BONUS = 0.05  # Substantial content (> 500 chars)
_CONFIDENCE_WEIGHT = 0.0  # Disabled: model_confidence is synthetic (always 0.5)


def score_email(email: Email, summary: EmailSummary) -> ProcessedEmail:
    """Apply hybrid scoring by combining rule-based signals with LLM output."""
    base = _PRIORITY_SCORES.get(summary.priority, 0.1)
    if summary.priority not in _PRIORITY_SCORES:
        logger.warning(
            "Unknown priority %r for email %s — defaulting base score to 0.1",
            summary.priority,
            email.id,
        )

    # Rule-based adjustments from the original email
    link_count = min(len(summary.key_links), 3)
    link_adj = link_count * _LINK_BONUS

    short_subject = len(email.subject) < 10
    subject_adj = _SHORT_SUBJECT_PENALTY if short_subject else 0.0

    long_body = len(email.body_text) > 500
    body_adj = _LONG_BODY_BONUS if long_body else 0.0

    confidence_adj = summary.model_confidence * _CONFIDENCE_WEIGHT

    adjustment = link_adj + subject_adj + body_adj + confidence_adj
    raw_score = base + adjustment
    final_score = round(max(0.0, min(1.0, raw_score)), 3)

    logger.debug(
        "Score breakdown for email %s (%r): "
        "base=%.3f link_adj=%.3f subject_adj=%.3f body_adj=%.3f "
        "confidence_adj=%.3f (confidence=%.3f) raw=%.3f final=%.3f priority=%s",
        email.id,
        email.subject[:50],
        base,
        link_adj,
        subject_adj,
        body_adj,
        confidence_adj,
        summary.model_confidence,
        raw_score,
        final_score,
        summary.priority,
    )

    return _ProcessedEmail(
        email=email,
        summary=summary.summary,
        priority=summary.priority,
        why_it_matters=summary.why_it_matters,
        recommended_action=summary.recommended_action,
        key_links=summary.key_links,
        score=final_score,
    )


def score_and_rank(pairs: list[tuple[Email, EmailSummary]]) -> list[ProcessedEmail]:
    """Score all emails and return sorted by score descending."""
    scored = [score_email(email, summary) for email, summary in pairs]
    ranked = sorted(scored, key=lambda e: e.score, reverse=True)
    logger.debug(
        "Ranked %d emails; top score=%.3f, bottom score=%.3f",
        len(ranked),
        ranked[0].score if ranked else 0.0,
        ranked[-1].score if ranked else 0.0,
    )
    return ranked
