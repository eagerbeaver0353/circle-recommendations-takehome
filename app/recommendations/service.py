"""Recommendation service orchestration (database access concentrated here)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Circle, Membership, Topic, User, UserInterest
from app.recommendations.constants import SNAPSHOT_REFERENCE
from app.recommendations.diversity import diversify
from app.recommendations.eligibility import filter_eligible
from app.recommendations.scoring import resolve_personalization, score_candidates
from app.recommendations.types import CircleCandidate, Recommendation


class UserNotFoundError(LookupError):
    """Raised when the requested user ID does not exist.

    Phase 3 can map this to HTTP 404.
    """

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"User {user_id} not found")


def _circle_to_candidate(circle: Circle) -> CircleCandidate:
    """Map an ORM Circle (with topic/tags loaded) to an immutable candidate view."""
    primary_slug = circle.primary_topic.slug if circle.primary_topic is not None else None
    # Sort tags for deterministic relevance evidence when multiple tags match.
    tags = tuple(sorted(tag.tag for tag in circle.tags))
    return CircleCandidate(
        id=circle.id,
        name=circle.name,
        access=circle.access,
        join_policy=circle.join_policy,
        max_members=circle.max_members,
        member_count=circle.member_count,
        feed_posts_30d=circle.feed_posts_30d,
        chat_messages_30d=circle.chat_messages_30d,
        last_activity_at=circle.last_activity_at,
        primary_topic_slug=primary_slug,
        tags=tags,
    )


def _load_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise UserNotFoundError(user_id)
    return user


def _load_explicit_interest_slugs(session: Session, user_id: int) -> list[str]:
    stmt = (
        select(Topic.slug)
        .join(UserInterest, UserInterest.topic_id == Topic.id)
        .where(UserInterest.user_id == user_id)
        .order_by(Topic.slug)
    )
    return list(session.scalars(stmt).all())


def _load_memberships(
    session: Session, user_id: int
) -> tuple[list[int], list[str | None]]:
    """Return ``(member_circle_ids, membership_primary_topic_slugs)``."""
    stmt = (
        select(Membership, Topic.slug)
        .outerjoin(Circle, Circle.id == Membership.circle_id)
        .outerjoin(Topic, Topic.id == Circle.primary_topic_id)
        .where(Membership.user_id == user_id)
        .order_by(Membership.circle_id)
    )
    rows = session.execute(stmt).all()
    circle_ids = [membership.circle_id for membership, _slug in rows]
    topic_slugs = [slug for _membership, slug in rows]
    return circle_ids, topic_slugs


def _load_circle_candidates(session: Session) -> list[CircleCandidate]:
    """Load all Circles with primary topic and tags in batched queries."""
    stmt = (
        select(Circle)
        .options(
            selectinload(Circle.primary_topic),
            selectinload(Circle.tags),
        )
        .order_by(Circle.id)
    )
    circles = session.scalars(stmt).unique().all()
    return [_circle_to_candidate(circle) for circle in circles]


def recommend_circles(
    session: Session,
    user_id: int,
    limit: int = 5,
    *,
    snapshot_reference: datetime = SNAPSHOT_REFERENCE,
) -> list[Recommendation]:
    """Return diversified Circle recommendations for *user_id*.

    Pipeline:
    1. Load user, explicit interests, and memberships
    2. Load Circle candidates with topic/tag relationships
    3. Apply eligibility filters
    4. Resolve personalization mode
    5. Score relevance and activity quality
    6. Diversify and truncate to *limit*

    The engine safely supports the Phase 3 public bounds of 1–20 (default 5).
    ``limit <= 0`` yields an empty list. Unknown users raise ``UserNotFoundError``.
    """
    if limit <= 0:
        return []

    _load_user(session, user_id)
    explicit_interests = _load_explicit_interest_slugs(session, user_id)
    member_circle_ids, membership_topics = _load_memberships(session, user_id)
    all_circles = _load_circle_candidates(session)

    eligible = filter_eligible(
        all_circles,
        member_circle_ids,
        snapshot_reference=snapshot_reference,
    )
    personalization_mode, interest_slugs = resolve_personalization(
        explicit_interests,
        membership_topics,
    )
    scored = score_candidates(
        eligible,
        personalization_mode=personalization_mode,
        interest_slugs=interest_slugs,
        snapshot_reference=snapshot_reference,
    )
    return diversify(scored, limit)
