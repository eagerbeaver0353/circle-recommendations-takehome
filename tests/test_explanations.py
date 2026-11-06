"""Unit tests for deterministic member-facing explanation generation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.recommendations.constants import (
    PERSONALIZATION_COLD_START,
    PERSONALIZATION_EXPLICIT,
    PERSONALIZATION_INFERRED,
    SNAPSHOT_REFERENCE,
)
from app.recommendations.explanations import (
    RECENT_ACTIVITY_WINDOW_DAYS,
    CircleExplanationContext,
    activity_is_recent,
    generate_explanation,
    humanize_topic,
    slug_to_readable,
)
from app.recommendations.types import ScoreEvidence

TOPIC_LABELS = {
    "getting-promoted": "Getting promoted",
    "public-speaking": "Public speaking",
    "leadership-skills": "Leadership skills",
    "negotiation": "Negotiation",
}


def _evidence(
    *,
    mode: str = PERSONALIZATION_EXPLICIT,
    relevance: float = 1.0,
    source: str | None = "primary_topic",
    matched: str | None = "leadership-skills",
    inferred: bool = False,
    feed_quality: float = 0.5,
    chat_quality: float = 0.5,
    recency_quality: float = 0.8,
    quality_score: float = 0.6,
) -> ScoreEvidence:
    return ScoreEvidence(
        personalization_mode=mode,
        relevance_score=relevance,
        relevance_source=source,
        matched_topic_or_tag=matched,
        relevance_is_inferred=inferred,
        feed_quality=feed_quality,
        chat_quality=chat_quality,
        recency_quality=recency_quality,
        quality_score=quality_score,
        relevance_weight=0.7,
        quality_weight=0.3,
        base_score=0.7,
    )


def _circle(
    *,
    topic_slug: str | None = "leadership-skills",
    topic_label: str | None = "Leadership skills",
    join_policy: str = "open",
    feed_posts_30d: int = 8,
    chat_messages_30d: int = 40,
    last_activity_at: datetime | None = None,
) -> CircleExplanationContext:
    return CircleExplanationContext(
        topic_slug=topic_slug,
        topic_label=topic_label,
        join_policy=join_policy,
        feed_posts_30d=feed_posts_30d,
        chat_messages_30d=chat_messages_30d,
        last_activity_at=last_activity_at
        or (SNAPSHOT_REFERENCE - timedelta(days=1)),
    )


def _assert_member_facing(text: str) -> None:
    assert isinstance(text, str)
    assert text.strip()
    assert text.endswith(".")
    assert text.count(".") == 1
    words = text.rstrip(".").split()
    assert 8 <= len(words) <= 35
    forbidden = (
        "ranking score",
        "base_score",
        "adjusted_score",
        "relevance_score",
        "diversification",
        "confidence weight",
        "personalization_mode",
    )
    lowered = text.lower()
    for token in forbidden:
        assert token not in lowered
    # No raw kebab-case topic slugs in the visible sentence.
    assert "getting-promoted" not in text
    assert "public-speaking" not in text
    assert "leadership-skills" not in text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_slug_and_label_humanization() -> None:
    assert slug_to_readable("getting-promoted") == "getting promoted"
    assert humanize_topic("getting-promoted", TOPIC_LABELS) == "getting promoted"
    assert humanize_topic("custom-tag", TOPIC_LABELS) == "custom tag"
    assert humanize_topic(None, TOPIC_LABELS) is None


def test_recent_activity_uses_snapshot_not_wall_clock() -> None:
    assert activity_is_recent(SNAPSHOT_REFERENCE - timedelta(days=1))
    assert activity_is_recent(
        SNAPSHOT_REFERENCE - timedelta(days=RECENT_ACTIVITY_WINDOW_DAYS)
    )
    assert not activity_is_recent(
        SNAPSHOT_REFERENCE - timedelta(days=RECENT_ACTIVITY_WINDOW_DAYS + 1)
    )
    # Far-future wall clock must not affect the snapshot-relative rule.
    ancient = datetime(2020, 1, 1, tzinfo=UTC)
    assert not activity_is_recent(ancient)


# ---------------------------------------------------------------------------
# Explanation modes
# ---------------------------------------------------------------------------


def test_explicit_primary_topic_match() -> None:
    text = generate_explanation(
        _evidence(
            matched="getting-promoted",
            source="primary_topic",
            inferred=False,
        ),
        _circle(
            topic_slug="getting-promoted",
            topic_label="Getting promoted",
        ),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "getting promoted" in text.lower()
    assert "interest" in text.lower()
    assert "recent member activity" in text.lower()


def test_explicit_tag_only_match() -> None:
    text = generate_explanation(
        _evidence(
            relevance=0.25,
            source="tag",
            matched="public-speaking",
            inferred=False,
        ),
        _circle(topic_slug="negotiation", topic_label="Negotiation"),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "public speaking" in text.lower()
    assert "also covers" in text.lower()
    assert "primarily" not in text.lower()
    assert "focuses on public speaking" not in text.lower()


def test_inferred_primary_topic_match() -> None:
    text = generate_explanation(
        _evidence(
            mode=PERSONALIZATION_INFERRED,
            source="primary_topic",
            matched="negotiation",
            inferred=True,
        ),
        _circle(topic_slug="negotiation", topic_label="Negotiation"),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "negotiation" in text.lower()
    assert "belong" in text.lower()
    assert "your interest" not in text.lower()
    assert "you're interested" not in text.lower()


def test_inferred_tag_match() -> None:
    text = generate_explanation(
        _evidence(
            mode=PERSONALIZATION_INFERRED,
            relevance=0.25,
            source="tag",
            matched="public-speaking",
            inferred=True,
        ),
        _circle(topic_slug="confidence", topic_label="Confidence"),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "public speaking" in text.lower()
    assert "your interest" not in text.lower()
    assert "you're interested" not in text.lower()


def test_cold_start_known_primary_topic() -> None:
    text = generate_explanation(
        _evidence(
            mode=PERSONALIZATION_COLD_START,
            relevance=0.0,
            source=None,
            matched=None,
            inferred=False,
        ),
        _circle(
            topic_slug="leadership-skills",
            topic_label="Leadership skills",
        ),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "leadership skills" in text.lower()
    assert "focuses on" in text.lower()
    assert "your interest" not in text.lower()
    assert "available snapshot" in text.lower() or "community snapshot" in text.lower()


def test_cold_start_no_primary_topic() -> None:
    text = generate_explanation(
        _evidence(
            mode=PERSONALIZATION_COLD_START,
            relevance=0.0,
            source=None,
            matched=None,
        ),
        _circle(
            topic_slug=None,
            topic_label=None,
            feed_posts_30d=12,
            chat_messages_30d=90,
        ),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "feed" in text.lower()
    assert "chat" in text.lower()
    assert "snapshot" in text.lower()
    assert "interest" not in text.lower()


def test_null_topic_and_empty_tags_no_invention() -> None:
    text = generate_explanation(
        _evidence(
            mode=PERSONALIZATION_COLD_START,
            relevance=0.0,
            source=None,
            matched=None,
        ),
        _circle(
            topic_slug=None,
            topic_label=None,
            feed_posts_30d=20,
            chat_messages_30d=211,
        ),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    # Must not invent a topic from the Circle name/description.
    assert "405" not in text
    assert "women of" not in text.lower()


def test_low_or_absent_activity_accessibility_fallback() -> None:
    text = generate_explanation(
        _evidence(
            mode=PERSONALIZATION_COLD_START,
            relevance=0.0,
            source=None,
            matched=None,
            feed_quality=0.0,
            chat_quality=0.0,
            recency_quality=0.1,
            quality_score=0.0,
        ),
        _circle(
            topic_slug=None,
            topic_label=None,
            feed_posts_30d=0,
            chat_messages_30d=0,
            last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=90),
            join_policy="open",
        ),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "open to new members" in text.lower()
    assert "feed" not in text.lower()
    assert "chat" not in text.lower()
    assert "recent" not in text.lower()


def test_feed_activity_only() -> None:
    text = generate_explanation(
        _evidence(
            mode=PERSONALIZATION_COLD_START,
            relevance=0.0,
            source=None,
            matched=None,
        ),
        _circle(
            topic_slug=None,
            topic_label=None,
            feed_posts_30d=5,
            chat_messages_30d=0,
        ),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "feed" in text.lower()
    assert "chat" not in text.lower()


def test_chat_activity_only() -> None:
    text = generate_explanation(
        _evidence(
            mode=PERSONALIZATION_COLD_START,
            relevance=0.0,
            source=None,
            matched=None,
        ),
        _circle(
            topic_slug=None,
            topic_label=None,
            feed_posts_30d=0,
            chat_messages_30d=25,
        ),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "chat" in text.lower()
    assert "feed" not in text.lower()


def test_request_to_join_circle() -> None:
    text = generate_explanation(
        _evidence(
            matched="getting-promoted",
            source="primary_topic",
            inferred=False,
        ),
        _circle(
            topic_slug="getting-promoted",
            topic_label="Getting promoted",
            join_policy="request",
        ),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "getting promoted" in text.lower()
    lowered = text.lower()
    assert "join immediately" not in lowered
    assert "open to new members" not in lowered
    assert "can join now" not in lowered


def test_request_policy_accessibility_fallback() -> None:
    text = generate_explanation(
        _evidence(
            mode=PERSONALIZATION_COLD_START,
            relevance=0.0,
            source=None,
            matched=None,
        ),
        _circle(
            topic_slug=None,
            topic_label=None,
            feed_posts_30d=0,
            chat_messages_30d=0,
            join_policy="request",
            last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=120),
        ),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "membership requests" in text.lower()
    assert "open to new members" not in text.lower()


def test_deterministic_output_for_identical_evidence() -> None:
    evidence = _evidence(matched="leadership-skills")
    circle = _circle()
    first = generate_explanation(evidence, circle, topic_labels=TOPIC_LABELS)
    second = generate_explanation(evidence, circle, topic_labels=TOPIC_LABELS)
    assert first == second
    _assert_member_facing(first)


def test_does_not_imply_live_activity_from_snapshot() -> None:
    # Stale-but-nonzero 30d counters without recent last_activity_at.
    text = generate_explanation(
        _evidence(
            mode=PERSONALIZATION_COLD_START,
            relevance=0.0,
            source=None,
            matched=None,
        ),
        _circle(
            topic_slug=None,
            topic_label=None,
            feed_posts_30d=4,
            chat_messages_30d=10,
            last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=45),
        ),
        topic_labels=TOPIC_LABELS,
    )
    _assert_member_facing(text)
    assert "today" not in text.lower()
    assert "right now" not in text.lower()
    assert "currently active" not in text.lower()
    assert "snapshot" in text.lower()
