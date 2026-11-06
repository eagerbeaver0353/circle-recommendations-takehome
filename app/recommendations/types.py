"""Structured internal types for recommendation scoring and results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CircleCandidate:
    """Immutable view of a Circle used by eligibility, scoring, and diversity."""

    id: int
    name: str
    access: str
    join_policy: str
    max_members: int | None
    member_count: int
    feed_posts_30d: int
    chat_messages_30d: int
    last_activity_at: datetime
    primary_topic_slug: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ActivityQualityBreakdown:
    """Component scores that form the combined activity-quality score."""

    feed_quality: float
    chat_quality: float
    recency_quality: float
    quality_score: float


@dataclass(frozen=True)
class ScoreEvidence:
    """Calculation evidence for Phase 3 explanation generation.

    Internal only — not an HTTP response schema.
    """

    personalization_mode: str
    relevance_score: float
    relevance_source: str | None
    matched_topic_or_tag: str | None
    relevance_is_inferred: bool
    feed_quality: float
    chat_quality: float
    recency_quality: float
    quality_score: float
    relevance_weight: float
    quality_weight: float
    base_score: float


@dataclass(frozen=True)
class ScoredCandidate:
    """An eligible Circle with its base score and scoring evidence."""

    circle_id: int
    circle_name: str
    primary_topic_slug: str | None
    base_score: float
    evidence: ScoreEvidence


@dataclass(frozen=True)
class Recommendation:
    """One ordered recommendation after diversification."""

    rank: int
    circle_id: int
    circle_name: str
    primary_topic_slug: str | None
    base_score: float
    adjusted_score: float
    evidence: ScoreEvidence
