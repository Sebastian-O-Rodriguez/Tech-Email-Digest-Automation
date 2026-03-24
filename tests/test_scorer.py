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
    topic: str = "tech_stacks",
    key_links: list[str] | None = None,
    email_id: str = "test",
) -> EmailSummary:
    return EmailSummary(
        email_id=email_id,
        summary="Test summary",
        topic=topic,
        key_links=key_links or [],
    )


class TestScoreEmail:
    def test_breaking_news_scores_highest(self):
        email = _make_email()
        summary = _make_summary(topic="breaking_news")
        result = score_email(email, summary)
        assert result.score >= 0.9

    def test_deep_dives_scores_lowest(self):
        email = _make_email()
        summary = _make_summary(topic="deep_dives")
        result = score_email(email, summary)
        assert result.score <= 0.6

    def test_links_increase_score(self):
        email = _make_email()
        without = score_email(email, _make_summary(topic="tech_stacks"))
        with_links = score_email(
            email, _make_summary(topic="tech_stacks", key_links=["https://a.com", "https://b.com"])
        )
        assert with_links.score > without.score

    def test_short_subject_penalized(self):
        normal = score_email(
            _make_email(subject="A Normal Subject"), _make_summary(topic="tech_stacks")
        )
        short = score_email(_make_email(subject="Re:"), _make_summary(topic="tech_stacks"))
        assert normal.score > short.score

    def test_score_clamped_to_0_1(self):
        email = _make_email()
        summary = _make_summary(topic="breaking_news", key_links=["a", "b", "c"])
        result = score_email(email, summary)
        assert 0.0 <= result.score <= 1.0

    def test_unknown_topic_defaults_to_low_base_score(self):
        email = _make_email()
        summary = _make_summary(topic="unknown_topic")
        result = score_email(email, summary)
        assert result.score <= 0.6

    def test_result_is_processed_email_with_correct_fields(self):
        email = _make_email(subject="My Subject", email_id="email-42")
        summary = _make_summary(
            topic="breaking_news",
            key_links=["https://example.com"],
            email_id="email-42",
        )
        result = score_email(email, summary)
        assert result.email is email
        assert result.summary == "Test summary"
        assert result.topic == "breaking_news"
        assert result.key_links == ["https://example.com"]


class TestScoreAndRank:
    def test_returns_sorted_descending(self):
        pairs = [
            (_make_email(email_id="a"), _make_summary(topic="deep_dives", email_id="a")),
            (_make_email(email_id="b"), _make_summary(topic="breaking_news", email_id="b")),
            (_make_email(email_id="c"), _make_summary(topic="tech_stacks", email_id="c")),
        ]
        ranked = score_and_rank(pairs)
        scores = [r.score for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_returns_all_emails(self):
        pairs = [
            (_make_email(email_id="a"), _make_summary(topic="deep_dives", email_id="a")),
            (_make_email(email_id="b"), _make_summary(topic="tech_stacks", email_id="b")),
        ]
        ranked = score_and_rank(pairs)
        assert len(ranked) == 2
