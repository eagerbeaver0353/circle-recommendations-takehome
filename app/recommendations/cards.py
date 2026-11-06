"""Assemble member-facing recommendation cards from ranked results.

Flow: ranked ``Recommendation`` list → one batched Circle metadata query →
explanation generation → Pydantic response cards. Preserves service rank order.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Circle, Topic
from app.recommendations.explanations import (
    CircleExplanationContext,
    generate_explanation,
)
from app.recommendations.types import Recommendation
from app.schemas import CircleRecommendationsResponse, RecommendationCard


class MissingCircleError(RuntimeError):
    """Raised when the ranking engine returns an ID that cannot be loaded."""

    def __init__(self, circle_ids: Sequence[int]) -> None:
        self.circle_ids = tuple(circle_ids)
        super().__init__(
            f"Internal consistency error: Circles not found: {sorted(self.circle_ids)}"
        )


@dataclass(frozen=True)
class CircleCardMetadata:
    """Card fields loaded from the database for a selected Circle."""

    id: int
    slug: str
    name: str
    description: str | None
    topic_slug: str | None
    topic_label: str | None
    format: str
    join_policy: str
    cover_image_url: str | None
    feed_posts_30d: int
    chat_messages_30d: int
    last_activity_at: datetime


def load_topic_labels(session: Session) -> dict[str, str]:
    """Return ``{slug: label}`` for the full topic taxonomy (one query)."""
    rows = session.execute(select(Topic.slug, Topic.label)).all()
    return {slug: label for slug, label in rows}


def load_circle_card_metadata(
    session: Session,
    circle_ids: Sequence[int],
) -> dict[int, CircleCardMetadata]:
    """Fetch card metadata for *circle_ids* in a single batched query.

    Result order from SQL ``IN`` is not relied upon; callers must reassemble
    cards using the ranking service's order.
    """
    if not circle_ids:
        return {}

    stmt = (
        select(Circle)
        .options(selectinload(Circle.primary_topic))
        .where(Circle.id.in_(tuple(circle_ids)))
    )
    circles = list(session.scalars(stmt).unique().all())
    metadata = {
        circle.id: _circle_to_metadata(circle) for circle in circles
    }

    missing = [cid for cid in circle_ids if cid not in metadata]
    if missing:
        raise MissingCircleError(missing)
    return metadata


def _circle_to_metadata(circle: Circle) -> CircleCardMetadata:
    topic = circle.primary_topic
    return CircleCardMetadata(
        id=circle.id,
        slug=circle.slug,
        name=circle.name,
        description=circle.description,
        topic_slug=topic.slug if topic is not None else None,
        topic_label=topic.label if topic is not None else None,
        format=circle.format,
        join_policy=circle.join_policy,
        cover_image_url=circle.cover_image_url,
        feed_posts_30d=circle.feed_posts_30d,
        chat_messages_30d=circle.chat_messages_30d,
        last_activity_at=circle.last_activity_at,
    )


def build_recommendation_response(
    session: Session,
    user_id: int,
    recommendations: Sequence[Recommendation],
) -> CircleRecommendationsResponse:
    """Hydrate ranked recommendations into the public API response shape."""
    circle_ids = [rec.circle_id for rec in recommendations]
    metadata_by_id = load_circle_card_metadata(session, circle_ids)
    topic_labels = load_topic_labels(session) if recommendations else {}

    cards: list[RecommendationCard] = []
    for rec in recommendations:
        meta = metadata_by_id[rec.circle_id]
        explanation_ctx = CircleExplanationContext(
            topic_slug=meta.topic_slug,
            topic_label=meta.topic_label,
            join_policy=meta.join_policy,
            feed_posts_30d=meta.feed_posts_30d,
            chat_messages_30d=meta.chat_messages_30d,
            last_activity_at=meta.last_activity_at,
        )
        reason = generate_explanation(
            rec.evidence,
            explanation_ctx,
            topic_labels=topic_labels,
        )
        cards.append(
            RecommendationCard(
                rank=rec.rank,
                circle_id=meta.id,
                slug=meta.slug,
                name=meta.name,
                description=meta.description,
                topic=meta.topic_slug,
                format=meta.format,  # type: ignore[arg-type]
                join_policy=meta.join_policy,  # type: ignore[arg-type]
                cover_image_url=meta.cover_image_url,
                reason=reason,
            )
        )

    return CircleRecommendationsResponse(user_id=user_id, recommendations=cards)
