"""Unit tests for ADR 004 relevance, quality, and confidence-aware scoring."""

from __future__ import annotations

import math
from datetime import timedelta

from app.recommendations.constants import (
    CHAT_ACTIVITY_WEIGHT,
    CHAT_REFERENCE_COUNT,
    FEED_ACTIVITY_WEIGHT,
    FEED_REFERENCE_COUNT,
    PERSONALIZATION_COLD_START,
    PERSONALIZATION_EXPLICIT,
    PERSONALIZATION_INFERRED,
    RECENCY_ACTIVITY_WEIGHT,
    SCORE_WEIGHTS,
    SNAPSHOT_REFERENCE,
)
from app.recommendations.scoring import (
    compute_activity_quality,
    compute_base_score,
    compute_topic_relevance,
    infer_interest_topics,
    normalize_activity_count,
    recency_quality,
    resolve_personalization,
    score_circle,
)
from app.recommendations.types import CircleCandidate


def _circle(**overrides) -> CircleCandidate:
    base = dict(
        id=1,
        name="Test Circle",
        access="public",
        join_policy="open",
        max_members=20,
        member_count=5,
        feed_posts_30d=10,
        chat_messages_30d=100,
        last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=1),
        primary_topic_slug="negotiation",
        tags=("confidence", "negotiation"),
    )
    base.update(overrides)
    return CircleCandidate(**base)


def test_primary_topic_match_is_one() -> None:
    score, source, matched = compute_topic_relevance(
        primary_topic_slug="leadership-skills",
        tags=("public-speaking",),
        interest_slugs={"leadership-skills"},
    )
    assert score == 1.0
    assert source == "primary_topic"
    assert matched == "leadership-skills"


def test_tag_only_match_is_quarter() -> None:
    score, source, matched = compute_topic_relevance(
        primary_topic_slug="career-breaks",
        tags=("negotiation", "confidence"),
        interest_slugs={"negotiation"},
    )
    assert score == 0.25
    assert source == "tag"
    assert matched == "negotiation"


def test_unrelated_topic_is_zero() -> None:
    score, source, matched = compute_topic_relevance(
        primary_topic_slug="allyship",
        tags=("gender-bias",),
        interest_slugs={"negotiation"},
    )
    assert score == 0.0
    assert source is None
    assert matched is None


def test_multiple_matching_tags_do_not_inflate_relevance() -> None:
    score, source, matched = compute_topic_relevance(
        primary_topic_slug="allyship",
        tags=("negotiation", "confidence", "leadership-skills"),
        interest_slugs={"negotiation", "confidence", "leadership-skills"},
    )
    assert score == 0.25
    assert source == "tag"
    # First matching tag in provided order.
    assert matched == "negotiation"


def test_primary_topic_takes_precedence_over_tag_match() -> None:
    score, source, matched = compute_topic_relevance(
        primary_topic_slug="negotiation",
        tags=("confidence",),
        interest_slugs={"negotiation", "confidence"},
    )
    assert score == 1.0
    assert source == "primary_topic"
    assert matched == "negotiation"


def test_explicit_interests_take_precedence_over_inferred() -> None:
    mode, interests = resolve_personalization(
        ["public-speaking"],
        ["negotiation", "negotiation", "negotiation"],
    )
    assert mode == PERSONALIZATION_EXPLICIT
    assert interests == frozenset({"public-speaking"})


def test_one_membership_insufficient_for_inference() -> None:
    inferred = infer_interest_topics(["negotiation"])
    assert inferred == frozenset()
    mode, interests = resolve_personalization([], ["negotiation", None, "allyship"])
    assert mode == PERSONALIZATION_COLD_START
    assert interests == frozenset()


def test_two_same_topic_memberships_enable_weak_inference() -> None:
    inferred = infer_interest_topics(["negotiation", "negotiation", "allyship"])
    assert inferred == frozenset({"negotiation"})
    mode, interests = resolve_personalization([], ["negotiation", "negotiation"])
    assert mode == PERSONALIZATION_INFERRED
    assert interests == frozenset({"negotiation"})


def test_null_primary_topics_ignored_for_inference() -> None:
    inferred = infer_interest_topics([None, None, "allyship"])
    assert inferred == frozenset()


def test_cold_start_uses_100_percent_quality() -> None:
    mode, interests = resolve_personalization([], [])
    assert mode == PERSONALIZATION_COLD_START
    assert interests == frozenset()
    base, rel_w, qual_w = compute_base_score(1.0, 0.8, PERSONALIZATION_COLD_START)
    assert rel_w == 0.0
    assert qual_w == 1.0
    assert base == 0.8


def test_score_weights_match_approved_table() -> None:
    assert SCORE_WEIGHTS[PERSONALIZATION_EXPLICIT] == (0.70, 0.30)
    assert SCORE_WEIGHTS[PERSONALIZATION_INFERRED] == (0.25, 0.75)
    assert SCORE_WEIGHTS[PERSONALIZATION_COLD_START] == (0.00, 1.00)
    for mode, (rw, qw) in SCORE_WEIGHTS.items():
        assert abs(rw + qw - 1.0) < 1e-12, mode


def test_explicit_and_inferred_base_score_blend() -> None:
    explicit_base, _, _ = compute_base_score(1.0, 0.5, PERSONALIZATION_EXPLICIT)
    assert abs(explicit_base - (0.70 * 1.0 + 0.30 * 0.5)) < 1e-12

    inferred_base, _, _ = compute_base_score(1.0, 0.5, PERSONALIZATION_INFERRED)
    assert abs(inferred_base - (0.25 * 1.0 + 0.75 * 0.5)) < 1e-12


def test_activity_normalization_bounds_and_zero() -> None:
    assert normalize_activity_count(0, FEED_REFERENCE_COUNT) == 0.0
    assert normalize_activity_count(FEED_REFERENCE_COUNT, FEED_REFERENCE_COUNT) == 1.0
    huge = normalize_activity_count(10_000_000, FEED_REFERENCE_COUNT)
    assert huge == 1.0
    mid = normalize_activity_count(5, FEED_REFERENCE_COUNT)
    expected = math.log1p(5) / math.log1p(FEED_REFERENCE_COUNT)
    assert abs(mid - expected) < 1e-12
    assert 0.0 < mid < 1.0


def test_activity_monotonicity_feed_and_chat() -> None:
    low = compute_activity_quality(
        feed_posts_30d=2,
        chat_messages_30d=10,
        last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=3),
    )
    high_feed = compute_activity_quality(
        feed_posts_30d=15,
        chat_messages_30d=10,
        last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=3),
    )
    high_chat = compute_activity_quality(
        feed_posts_30d=2,
        chat_messages_30d=150,
        last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=3),
    )
    assert high_feed.feed_quality >= low.feed_quality
    assert high_feed.quality_score >= low.quality_score
    assert high_chat.chat_quality >= low.chat_quality
    assert high_chat.quality_score >= low.quality_score


def test_more_recent_activity_increases_or_preserves_recency() -> None:
    older = recency_quality(SNAPSHOT_REFERENCE - timedelta(days=28))
    newer = recency_quality(SNAPSHOT_REFERENCE - timedelta(days=1))
    future = recency_quality(SNAPSHOT_REFERENCE + timedelta(days=5))
    assert newer >= older
    assert future == 1.0
    assert math.isfinite(older) and math.isfinite(newer)


def test_quality_components_finite_and_bounded() -> None:
    quality = compute_activity_quality(
        feed_posts_30d=0,
        chat_messages_30d=0,
        last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=100),
    )
    for value in (
        quality.feed_quality,
        quality.chat_quality,
        quality.recency_quality,
        quality.quality_score,
    ):
        assert math.isfinite(value)
        assert 0.0 <= value <= 1.0

    # Documented blend of component weights.
    expected = (
        FEED_ACTIVITY_WEIGHT * quality.feed_quality
        + CHAT_ACTIVITY_WEIGHT * quality.chat_quality
        + RECENCY_ACTIVITY_WEIGHT * quality.recency_quality
    )
    assert abs(quality.quality_score - expected) < 1e-12


def test_chat_reference_threshold_used() -> None:
    at_ref = normalize_activity_count(CHAT_REFERENCE_COUNT, CHAT_REFERENCE_COUNT)
    assert at_ref == 1.0


def test_score_circle_evidence_fields() -> None:
    circle = _circle(primary_topic_slug="negotiation", tags=("confidence",))
    scored = score_circle(
        circle,
        personalization_mode=PERSONALIZATION_EXPLICIT,
        interest_slugs={"negotiation"},
    )
    assert scored.base_score == scored.evidence.base_score
    assert scored.evidence.personalization_mode == PERSONALIZATION_EXPLICIT
    assert scored.evidence.relevance_score == 1.0
    assert scored.evidence.relevance_source == "primary_topic"
    assert scored.evidence.matched_topic_or_tag == "negotiation"
    assert scored.evidence.relevance_is_inferred is False
    assert 0.0 <= scored.base_score <= 1.0


def test_inferred_relevance_flag_in_evidence() -> None:
    circle = _circle(primary_topic_slug="negotiation")
    scored = score_circle(
        circle,
        personalization_mode=PERSONALIZATION_INFERRED,
        interest_slugs={"negotiation"},
    )
    assert scored.evidence.relevance_is_inferred is True
    assert scored.evidence.relevance_weight == 0.25
    assert scored.evidence.quality_weight == 0.75
