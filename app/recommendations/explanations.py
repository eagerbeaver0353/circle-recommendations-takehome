"""Deterministic member-facing explanation generation (ADR 006).

Pure functions: ranking evidence + Circle metadata in, one natural sentence out.
Does not recalculate relevance, query the database, or call external services.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.recommendations.constants import SNAPSHOT_REFERENCE
from app.recommendations.types import ScoreEvidence

# Activity within this many days of the fixed snapshot may be called "recent".
# Never use wall-clock time — the dataset is a synthetic September 2026 snapshot.
RECENT_ACTIVITY_WINDOW_DAYS: int = 30


@dataclass(frozen=True)
class CircleExplanationContext:
    """Public Circle facts used to ground explanation wording."""

    topic_slug: str | None
    topic_label: str | None
    join_policy: str
    feed_posts_30d: int
    chat_messages_30d: int
    last_activity_at: datetime


def slug_to_readable(slug: str) -> str:
    """Conservatively convert a kebab-case slug into readable lower-case text."""
    return slug.replace("-", " ").strip().lower()


def humanize_topic(
    slug: str | None,
    topic_labels: Mapping[str, str] | None = None,
) -> str | None:
    """Return a human-readable topic name for mid-sentence use.

    Prefers the canonical ``topics.label`` (lowercased for sentence flow).
    Falls back to a conservative kebab-case expansion for free-form tags.
    """
    if slug is None:
        return None
    if topic_labels and slug in topic_labels:
        return topic_labels[slug].strip().lower()
    return slug_to_readable(slug)


def activity_is_recent(
    last_activity_at: datetime,
    *,
    snapshot_reference: datetime = SNAPSHOT_REFERENCE,
    window_days: int = RECENT_ACTIVITY_WINDOW_DAYS,
) -> bool:
    """True when last activity falls within *window_days* of the snapshot."""
    elapsed_seconds = (snapshot_reference - last_activity_at).total_seconds()
    if elapsed_seconds < 0:
        # Activity stamped after the snapshot still counts as recent evidence.
        return True
    return elapsed_seconds <= window_days * 86_400.0


def has_feed_activity(feed_posts_30d: int) -> bool:
    return feed_posts_30d > 0


def has_chat_activity(chat_messages_30d: int) -> bool:
    return chat_messages_30d > 0


def _activity_supporting_clause(circle: CircleExplanationContext) -> str | None:
    """Optional clause describing activity, or None when claims are unsupported."""
    feed = has_feed_activity(circle.feed_posts_30d)
    chat = has_chat_activity(circle.chat_messages_30d)
    recent = activity_is_recent(circle.last_activity_at)

    if feed and chat:
        if recent:
            return "had recent member activity in the available snapshot"
        return "had feed posts and chat activity in the available community snapshot"
    if feed:
        return "has feed discussions in the available community snapshot"
    if chat:
        return "has chat activity in the available community snapshot"
    return None


def _activity_standalone_sentence(circle: CircleExplanationContext) -> str | None:
    """Full-sentence activity claim for Circles without a personalization hook."""
    feed = has_feed_activity(circle.feed_posts_30d)
    chat = has_chat_activity(circle.chat_messages_30d)

    if feed and chat:
        return (
            "This Circle had feed posts and chat activity "
            "in the available community snapshot."
        )
    if feed:
        return "This Circle had feed discussions in the available community snapshot."
    if chat:
        return "This Circle had chat activity in the available community snapshot."
    return None


def _accessibility_fallback(circle: CircleExplanationContext) -> str:
    """Neutral public-accessibility wording when topic and activity are thin."""
    if circle.join_policy == "request":
        return "This Circle is publicly listed and accepts membership requests."
    return "This Circle is publicly listed and open to new members."


def _with_activity(base: str, circle: CircleExplanationContext) -> str:
    """Append an activity clause when evidence supports it."""
    clause = _activity_supporting_clause(circle)
    if clause is None:
        return base if base.endswith(".") else f"{base}."
    trimmed = base.rstrip(".")
    return f"{trimmed} and {clause}."


def generate_explanation(
    evidence: ScoreEvidence,
    circle: CircleExplanationContext,
    *,
    topic_labels: Mapping[str, str] | None = None,
) -> str:
    """Build one deterministic member-facing explanation sentence.

    Selection priorities follow ADR 006:
    A. Explicit primary-topic match
    B. Explicit secondary-tag match
    C. Inferred primary-topic match
    D. Inferred tag match
    E. No matching interest, known primary topic
    F. Missing primary topic (activity or accessibility fallback)
    """
    labels = topic_labels or {}
    if circle.topic_label and circle.topic_slug:
        # Prefer the label already resolved for this Circle's primary topic.
        labels = {**labels, circle.topic_slug: circle.topic_label}

    matched = evidence.matched_topic_or_tag
    source = evidence.relevance_source
    inferred = evidence.relevance_is_inferred

    if source == "primary_topic" and matched is not None and not inferred:
        topic = humanize_topic(matched, labels) or "this topic"
        return _with_activity(
            f"This Circle matches your interest in {topic}",
            circle,
        )

    if source == "tag" and matched is not None and not inferred:
        tag = humanize_topic(matched, labels) or "this topic"
        return (
            f"This Circle also covers {tag}, a topic you're interested in."
        )

    if source == "primary_topic" and matched is not None and inferred:
        topic = humanize_topic(matched, labels) or "this topic"
        return (
            f"You belong to other Circles about {topic}, "
            f"and this Circle focuses on that topic too."
        )

    if source == "tag" and matched is not None and inferred:
        tag = humanize_topic(matched, labels) or "this topic"
        return (
            f"You belong to other Circles touching related themes, "
            f"and this Circle also covers {tag}."
        )

    primary = humanize_topic(circle.topic_slug, labels)
    if primary is not None:
        clause = _activity_supporting_clause(circle)
        if clause is not None:
            # Prefer snapshot-aware wording for cold-start / unmatched Circles.
            if "recent member activity" in clause:
                return (
                    f"This Circle focuses on {primary} and had recent community "
                    f"activity in the available snapshot."
                )
            return f"This Circle focuses on {primary} and {clause}."
        return f"This Circle focuses on {primary}."

    activity_sentence = _activity_standalone_sentence(circle)
    if activity_sentence is not None:
        return activity_sentence

    return _accessibility_fallback(circle)
