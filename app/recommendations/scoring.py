"""Topic relevance, activity quality, and confidence-aware scoring (ADR 004).

Pure functions — no database access.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime

from app.recommendations.constants import (
    CHAT_ACTIVITY_WEIGHT,
    CHAT_REFERENCE_COUNT,
    FEED_ACTIVITY_WEIGHT,
    FEED_REFERENCE_COUNT,
    MIN_MEMBERSHIPS_FOR_INFERENCE,
    PERSONALIZATION_COLD_START,
    PERSONALIZATION_EXPLICIT,
    PERSONALIZATION_INFERRED,
    PRIMARY_TOPIC_RELEVANCE,
    RECENCY_ACTIVITY_WEIGHT,
    RECENCY_HALF_LIFE_DAYS,
    SCORE_WEIGHTS,
    SNAPSHOT_REFERENCE,
    TAG_MATCH_RELEVANCE,
)
from app.recommendations.types import (
    ActivityQualityBreakdown,
    CircleCandidate,
    ScoredCandidate,
    ScoreEvidence,
)


def normalize_activity_count(count: int, reference_count: int) -> float:
    """Map a nonnegative activity count onto ``[0, 1]`` with diminishing returns.

    ``normalized = min(1.0, log1p(count) / log1p(reference_count))``

    Zero counts yield 0.0. Counts at or above the fixed reference saturate at 1.0.
    """
    if count < 0:
        raise ValueError(f"activity count must be nonnegative, got {count}")
    if reference_count <= 0:
        raise ValueError(f"reference_count must be positive, got {reference_count}")
    return min(1.0, math.log1p(count) / math.log1p(reference_count))


def recency_quality(
    last_activity_at: datetime,
    *,
    snapshot_reference: datetime = SNAPSHOT_REFERENCE,
    half_life_days: float = RECENCY_HALF_LIFE_DAYS,
) -> float:
    """Bounded monotonic decay of activity recency relative to the snapshot.

    Uses exponential half-life decay: ``0.5 ** (elapsed_days / half_life)``.
    Future or negative elapsed time is clamped to zero (score 1.0).
    """
    if half_life_days <= 0:
        raise ValueError(f"half_life_days must be positive, got {half_life_days}")
    elapsed_seconds = (snapshot_reference - last_activity_at).total_seconds()
    if elapsed_seconds < 0:
        elapsed_seconds = 0.0
    elapsed_days = elapsed_seconds / 86_400.0
    return 0.5 ** (elapsed_days / half_life_days)


def compute_activity_quality(
    *,
    feed_posts_30d: int,
    chat_messages_30d: int,
    last_activity_at: datetime,
    snapshot_reference: datetime = SNAPSHOT_REFERENCE,
) -> ActivityQualityBreakdown:
    """Combine feed, chat, and recency into a quality score in ``[0, 1]``."""
    feed = normalize_activity_count(feed_posts_30d, FEED_REFERENCE_COUNT)
    chat = normalize_activity_count(chat_messages_30d, CHAT_REFERENCE_COUNT)
    recency = recency_quality(
        last_activity_at,
        snapshot_reference=snapshot_reference,
    )
    combined = (
        FEED_ACTIVITY_WEIGHT * feed
        + CHAT_ACTIVITY_WEIGHT * chat
        + RECENCY_ACTIVITY_WEIGHT * recency
    )
    # Guard floating-point drift while preserving the documented blend.
    quality = min(1.0, max(0.0, combined))
    return ActivityQualityBreakdown(
        feed_quality=feed,
        chat_quality=chat,
        recency_quality=recency,
        quality_score=quality,
    )


def compute_topic_relevance(
    *,
    primary_topic_slug: str | None,
    tags: Sequence[str],
    interest_slugs: Iterable[str],
) -> tuple[float, str | None, str | None]:
    """Return ``(relevance, source, matched_slug_or_tag)`` on a 0–1 scale.

    Strongest applicable match only (not a sum):
    - Primary topic in interests → 1.0
    - Otherwise any tag in interests → 0.25
    - Else → 0.0

    When multiple tags match, the first tag in *tags* order is recorded for
    evidence (scores are identical). Multiple matching interests do not add a
    bonus.
    """
    interests = frozenset(interest_slugs)
    if not interests:
        return 0.0, None, None

    if primary_topic_slug is not None and primary_topic_slug in interests:
        return PRIMARY_TOPIC_RELEVANCE, "primary_topic", primary_topic_slug

    for tag in tags:
        if tag in interests:
            return TAG_MATCH_RELEVANCE, "tag", tag

    return 0.0, None, None


def infer_interest_topics(
    membership_primary_topics: Sequence[str | None],
    *,
    min_memberships: int = MIN_MEMBERSHIPS_FOR_INFERENCE,
) -> frozenset[str]:
    """Infer topics from repeated membership primary topics.

    A topic is inferred only when the user belongs to at least
    *min_memberships* distinct Circles sharing that non-null primary topic.
    Null primary topics are ignored. Repetition counts beyond the threshold
    do not create an additional scoring bonus.
    """
    counts = Counter(
        topic for topic in membership_primary_topics if topic is not None
    )
    return frozenset(
        topic for topic, count in counts.items() if count >= min_memberships
    )


def resolve_personalization(
    explicit_interest_slugs: Sequence[str],
    membership_primary_topics: Sequence[str | None],
) -> tuple[str, frozenset[str]]:
    """Choose personalization mode and the interest set used for relevance.

    Explicit stated interests always win — memberships are not mixed in.
    """
    explicit = frozenset(explicit_interest_slugs)
    if explicit:
        return PERSONALIZATION_EXPLICIT, explicit

    inferred = infer_interest_topics(membership_primary_topics)
    if inferred:
        return PERSONALIZATION_INFERRED, inferred

    return PERSONALIZATION_COLD_START, frozenset()


def compute_base_score(
    relevance: float,
    quality: float,
    personalization_mode: str,
) -> tuple[float, float, float]:
    """Return ``(base_score, relevance_weight, quality_weight)`` in ``[0, 1]``."""
    try:
        relevance_weight, quality_weight = SCORE_WEIGHTS[personalization_mode]
    except KeyError as exc:
        raise ValueError(f"unknown personalization mode: {personalization_mode!r}") from exc

    base = relevance_weight * relevance + quality_weight * quality
    return min(1.0, max(0.0, base)), relevance_weight, quality_weight


def score_circle(
    circle: CircleCandidate,
    *,
    personalization_mode: str,
    interest_slugs: Iterable[str],
    snapshot_reference: datetime = SNAPSHOT_REFERENCE,
) -> ScoredCandidate:
    """Score one eligible Circle and attach structured calculation evidence."""
    relevance, source, matched = compute_topic_relevance(
        primary_topic_slug=circle.primary_topic_slug,
        tags=circle.tags,
        interest_slugs=interest_slugs,
    )
    activity = compute_activity_quality(
        feed_posts_30d=circle.feed_posts_30d,
        chat_messages_30d=circle.chat_messages_30d,
        last_activity_at=circle.last_activity_at,
        snapshot_reference=snapshot_reference,
    )
    base_score, relevance_weight, quality_weight = compute_base_score(
        relevance,
        activity.quality_score,
        personalization_mode,
    )
    evidence = ScoreEvidence(
        personalization_mode=personalization_mode,
        relevance_score=relevance,
        relevance_source=source,
        matched_topic_or_tag=matched,
        relevance_is_inferred=personalization_mode == PERSONALIZATION_INFERRED,
        feed_quality=activity.feed_quality,
        chat_quality=activity.chat_quality,
        recency_quality=activity.recency_quality,
        quality_score=activity.quality_score,
        relevance_weight=relevance_weight,
        quality_weight=quality_weight,
        base_score=base_score,
    )
    return ScoredCandidate(
        circle_id=circle.id,
        circle_name=circle.name,
        primary_topic_slug=circle.primary_topic_slug,
        base_score=base_score,
        evidence=evidence,
    )


def score_candidates(
    circles: Sequence[CircleCandidate],
    *,
    personalization_mode: str,
    interest_slugs: Iterable[str],
    snapshot_reference: datetime = SNAPSHOT_REFERENCE,
) -> list[ScoredCandidate]:
    """Score all eligible candidates. Order is ascending Circle ID (stable)."""
    interests = frozenset(interest_slugs)
    scored = [
        score_circle(
            circle,
            personalization_mode=personalization_mode,
            interest_slugs=interests,
            snapshot_reference=snapshot_reference,
        )
        for circle in circles
    ]
    return sorted(scored, key=lambda c: c.circle_id)
