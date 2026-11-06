"""Eligibility filtering for Circle recommendations (ADR 003).

Pure functions: filtering does not mutate inputs or database records.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from app.recommendations.constants import (
    DORMANCY_INACTIVITY_DAYS,
    DORMANCY_MAX_CHAT_MESSAGES_30D,
    PUBLIC_ACCESS,
    SNAPSHOT_REFERENCE,
)
from app.recommendations.types import CircleCandidate


def is_existing_member(circle_id: int, member_circle_ids: Iterable[int]) -> bool:
    """True when the requesting user already belongs to the Circle (any role)."""
    return circle_id in member_circle_ids


def is_at_capacity(max_members: int | None, member_count: int) -> bool:
    """True when the Circle has a finite max and current members fill it."""
    return max_members is not None and member_count >= max_members


def is_public_access(access: str) -> bool:
    """Only public Circles are eligible for general discovery."""
    return access == PUBLIC_ACCESS


def is_dormant(
    *,
    feed_posts_30d: int,
    chat_messages_30d: int,
    last_activity_at: datetime,
    snapshot_reference: datetime = SNAPSHOT_REFERENCE,
) -> bool:
    """True only when all three dormancy conditions hold.

    - No feed posts in the last 30 days
    - At most ``DORMANCY_MAX_CHAT_MESSAGES_30D`` chat messages in 30 days
    - ``last_activity_at`` is *more than* ``DORMANCY_INACTIVITY_DAYS`` before the
      snapshot reference (exactly 60 days inactive is NOT dormant)
    """
    if feed_posts_30d != 0:
        return False
    if chat_messages_30d > DORMANCY_MAX_CHAT_MESSAGES_30D:
        return False
    inactivity = snapshot_reference - last_activity_at
    return inactivity > timedelta(days=DORMANCY_INACTIVITY_DAYS)


def is_eligible(
    circle: CircleCandidate,
    member_circle_ids: Iterable[int],
    *,
    snapshot_reference: datetime = SNAPSHOT_REFERENCE,
) -> bool:
    """Return whether *circle* may enter the recommendation candidate set."""
    if is_existing_member(circle.id, member_circle_ids):
        return False
    if is_at_capacity(circle.max_members, circle.member_count):
        return False
    if not is_public_access(circle.access):
        return False
    if is_dormant(
        feed_posts_30d=circle.feed_posts_30d,
        chat_messages_30d=circle.chat_messages_30d,
        last_activity_at=circle.last_activity_at,
        snapshot_reference=snapshot_reference,
    ):
        return False
    return True


def filter_eligible(
    circles: Sequence[CircleCandidate],
    member_circle_ids: Iterable[int],
    *,
    snapshot_reference: datetime = SNAPSHOT_REFERENCE,
) -> list[CircleCandidate]:
    """Return eligible Circles in deterministic ascending ID order.

    Missing primary topics, descriptions, tags, or cover images do not
    affect eligibility. Ineligible Circles are dropped — never forced into
    results to pad a requested limit.
    """
    member_ids = frozenset(member_circle_ids)
    eligible = [
        circle
        for circle in circles
        if is_eligible(circle, member_ids, snapshot_reference=snapshot_reference)
    ]
    return sorted(eligible, key=lambda c: c.id)
