"""Tests for hybrid scoring logic."""

from datetime import UTC, datetime

from email_ingester.models import Email, EmailSummary
from email_ingester.scorer import score_and_rank, score_email


def _make_email(
    subject: str = "Normal Subject Here",
    body_text: str = "Some body content that is reasonable length.",
    email_id: str = "test",
) -> Email:
    return Email(
        id=email_id,
        subject=subject,
        sender="test@example.com",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        body_text=body_text,
        body_html="",
        links=[],
    )


def _make_summary(
    priority: str = "medium",
    key_links: list[str] | None = None,
    model_confidence: float = 0.0,
    email_id: str = "test",
) -> EmailSummary:
    return EmailSummary(
        email_id=email_id,
        summary="Test summary",
        priority=priority,
        why_it_matters="Test reason",
        recommended_action="Test action",
        key_links=key_links or [],
        model_confidence=model_confidence,
    )


class TestScoreEmail:
    def test_high_priority_scores_highest(self):
        email = _make_email()
        summary = _make_summary(priority="high")
        result = score_email(email, summary)
        assert result.score >= 0.9

    def test_low_priority_scores_lowest(self):
        email = _make_email()
        summary = _make_summary(priority="low")
        result = score_email(email, summary)
        assert result.score <= 0.3

    def test_links_increase_score(self):
        email = _make_email()
        without = score_email(email, _make_summary(priority="medium"))
        with_links = score_email(
            email, _make_summary(priority="medium", key_links=["https://a.com", "https://b.com"])
        )
        assert with_links.score > without.score

    def test_short_subject_penalized(self):
        normal = score_email(
            _make_email(subject="A Normal Subject"), _make_summary(priority="medium")
        )
        short = score_email(_make_email(subject="Re:"), _make_summary(priority="medium"))
        assert normal.score > short.score

    def test_score_clamped_to_0_1(self):
        email = _make_email()
        summary = _make_summary(priority="high", key_links=["a", "b", "c"])
        result = score_email(email, summary)
        assert 0.0 <= result.score <= 1.0

    def test_model_confidence_has_no_effect_on_score(self):
        """model_confidence weight is 0.0 — varying it should not change the score."""
        email = _make_email()
        low_confidence = score_email(email, _make_summary(priority="medium", model_confidence=0.0))
        high_confidence = score_email(email, _make_summary(priority="medium", model_confidence=1.0))
        assert high_confidence.score == low_confidence.score

    def test_unknown_priority_defaults_to_low_base_score(self):
        email = _make_email()
        summary = _make_summary(priority="urgent")  # not a valid priority
        result = score_email(email, summary)
        # Base score for unknown priority is 0.1 (same as "low")
        assert result.score <= 0.3

    def test_result_is_processed_email_with_correct_fields(self):
        email = _make_email(subject="My Subject", email_id="email-42")
        summary = _make_summary(
            priority="high",
            key_links=["https://example.com"],
            model_confidence=0.5,
            email_id="email-42",
        )
        result = score_email(email, summary)
        assert result.email is email
        assert result.summary == "Test summary"
        assert result.priority == "high"
        assert result.why_it_matters == "Test reason"
        assert result.recommended_action == "Test action"
        assert result.key_links == ["https://example.com"]


class TestScoreAndRank:
    def test_returns_sorted_descending(self):
        pairs = [
            (_make_email(email_id="a"), _make_summary(priority="low", email_id="a")),
            (_make_email(email_id="b"), _make_summary(priority="high", email_id="b")),
            (_make_email(email_id="c"), _make_summary(priority="medium", email_id="c")),
        ]
        ranked = score_and_rank(pairs)
        scores = [r.score for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_returns_all_emails(self):
        pairs = [
            (_make_email(email_id="a"), _make_summary(priority="low", email_id="a")),
            (_make_email(email_id="b"), _make_summary(priority="medium", email_id="b")),
        ]
        ranked = score_and_rank(pairs)
        assert len(ranked) == 2
