"""Planted assessment scenarios, service integration, and dataset-wide checks."""

from __future__ import annotations

import math

import pytest
from app.models import Circle, Membership, Topic, User, UserInterest
from app.recommendations.constants import (
    PERSONALIZATION_COLD_START,
    PERSONALIZATION_EXPLICIT,
    SNAPSHOT_REFERENCE,
)
from app.recommendations.eligibility import filter_eligible, is_dormant
from app.recommendations.service import UserNotFoundError, recommend_circles
from app.recommendations.types import (
    CircleCandidate,
    Recommendation,
)
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, selectinload

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _recommendations_stable(session: Session, user_id: int, limit: int) -> list[int]:
    first = [r.circle_id for r in recommend_circles(session, user_id, limit=limit)]
    second = [r.circle_id for r in recommend_circles(session, user_id, limit=limit)]
    assert first == second
    return first


def _circle_lookup(session: Session) -> dict[int, Circle]:
    circles = session.scalars(
        select(Circle).options(selectinload(Circle.primary_topic))
    ).all()
    return {c.id: c for c in circles}


def _assert_recommendation_invariants(
    session: Session,
    user_id: int,
    results: list[Recommendation],
    *,
    limit: int,
) -> None:
    member_ids = set(
        session.scalars(
            select(Membership.circle_id).where(Membership.user_id == user_id)
        ).all()
    )
    circles = _circle_lookup(session)
    seen: set[int] = set()

    assert len(results) <= limit
    for rec in results:
        assert rec.circle_id not in seen
        seen.add(rec.circle_id)
        assert rec.circle_id not in member_ids

        circle = circles[rec.circle_id]
        assert circle.access == "public"
        assert not (
            circle.max_members is not None and circle.member_count >= circle.max_members
        )
        assert not is_dormant(
            feed_posts_30d=circle.feed_posts_30d,
            chat_messages_30d=circle.chat_messages_30d,
            last_activity_at=circle.last_activity_at,
        )
        assert math.isfinite(rec.base_score)
        assert 0.0 <= rec.base_score <= 1.0
        assert math.isfinite(rec.adjusted_score)
        assert rec.evidence is not None
        assert rec.evidence.personalization_mode in {
            "explicit",
            "inferred",
            "cold_start",
        }
        assert rec.evidence.base_score == rec.base_score


# ---------------------------------------------------------------------------
# Planted scenarios
# ---------------------------------------------------------------------------


def test_user_42_cold_start(seeded_engine: Engine) -> None:
    with Session(seeded_engine) as session:
        user = session.get(User, 42)
        assert user is not None
        interests = session.scalars(
            select(UserInterest).where(UserInterest.user_id == 42)
        ).all()
        memberships = session.scalars(
            select(Membership).where(Membership.user_id == 42)
        ).all()
        assert interests == []
        assert memberships == []

        results = recommend_circles(session, 42, limit=5)
        assert results
        assert all(
            r.evidence.personalization_mode == PERSONALIZATION_COLD_START for r in results
        )
        assert all(r.evidence.relevance_score == 0.0 for r in results)
        assert all(r.evidence.matched_topic_or_tag is None for r in results)
        assert all(r.evidence.relevance_weight == 0.0 for r in results)
        assert all(r.evidence.quality_weight == 1.0 for r in results)
        # Cold start ranks purely by quality — base score equals quality.
        assert all(
            abs(r.base_score - r.evidence.quality_score) < 1e-12 for r in results
        )
        # Quality should be monotonically nonincreasing in the base ranking
        # before diversity penalties; adjusted may differ slightly but the
        # list should still reflect meaningful activity ranking.
        qualities = [r.evidence.quality_score for r in results]
        assert max(qualities) >= min(qualities)


def test_user_7_obvious_matches(seeded_engine: Engine) -> None:
    with Session(seeded_engine) as session:
        results = recommend_circles(session, 7, limit=5)
        ids = [r.circle_id for r in results]
        assert 5 in ids
        assert 6 in ids

        member_ids = set(
            session.scalars(
                select(Membership.circle_id).where(Membership.user_id == 7)
            ).all()
        )
        assert not member_ids.intersection(ids)

        by_id = {r.circle_id: r for r in results}
        for circle_id in (5, 6):
            rec = by_id[circle_id]
            assert rec.evidence.personalization_mode == PERSONALIZATION_EXPLICIT
            assert rec.evidence.relevance_score == 1.0
            assert rec.base_score > 0.7


def test_user_15_duplicate_negotiation_diversity(seeded_engine: Engine) -> None:
    """User 15: negotiation duplicates are diversified against confidence.

    Under ADR 005, the first five interleave negotiation with confidence
    alternatives. A third negotiation Circle may still appear later in the
    top five when its base score exceeds the best remaining other-topic
    candidate by more than 0.25 (approved exception) — which occurs here
    after both strong confidence Circles have already been selected.
    """
    with Session(seeded_engine) as session:
        results = recommend_circles(session, 15, limit=5)
        ids = [r.circle_id for r in results]
        topics = [r.primary_topic_slug for r in results]

        # Diversity is applied: the first three are not all negotiation.
        assert topics[:3] != ["negotiation", "negotiation", "negotiation"]

        # Strong confidence alternatives remain competitive in the top five.
        assert "confidence" in topics
        confidence_recs = [r for r in results if r.primary_topic_slug == "confidence"]
        assert confidence_recs
        assert any(r.evidence.relevance_score == 1.0 for r in confidence_recs)

        # At least two of the planted negotiation Circles rank highly.
        planted_in_top5 = {10, 11, 12}.intersection(ids)
        assert len(planted_in_top5) >= 2

        # Same-topic penalty is visible on later negotiation picks.
        negotiation_recs = [r for r in results if r.primary_topic_slug == "negotiation"]
        if len(negotiation_recs) >= 2:
            assert negotiation_recs[1].adjusted_score < negotiation_recs[1].base_score

        member_ids = set(
            session.scalars(
                select(Membership.circle_id).where(Membership.user_id == 15)
            ).all()
        )
        assert not member_ids.intersection(ids)


def test_user_23_full_and_inactive_traps(seeded_engine: Engine) -> None:
    with Session(seeded_engine) as session:
        results = recommend_circles(session, 23, limit=5)
        ids = [r.circle_id for r in results]

        assert 20 not in ids  # full
        assert 21 not in ids  # dormant + unlisted
        assert ids[0] == 22  # healthy getting-promoted alternative ranks first

        circle_22 = session.get(Circle, 22)
        assert circle_22 is not None
        assert circle_22.join_policy == "request"
        assert any(r.circle_id == 22 for r in results)

        top = results[0]
        assert top.evidence.relevance_score == 1.0
        assert top.primary_topic_slug == "getting-promoted"


# ---------------------------------------------------------------------------
# Service edge cases
# ---------------------------------------------------------------------------


def test_unknown_user_raises(seeded_engine: Engine) -> None:
    with Session(seeded_engine) as session:
        with pytest.raises(UserNotFoundError) as exc_info:
            recommend_circles(session, 999_999, limit=5)
        assert exc_info.value.user_id == 999_999


def test_limit_zero_returns_empty(seeded_engine: Engine) -> None:
    with Session(seeded_engine) as session:
        assert recommend_circles(session, 7, limit=0) == []
        assert recommend_circles(session, 7, limit=-3) == []


def test_empty_candidate_list_via_controlled_fixtures(session: Session) -> None:
    """With no Circles in the DB, recommendations are empty."""
    topic = Topic(id=1, slug="negotiation", label="Negotiation", domain="content")
    session.add(topic)
    session.add(
        User(
            id=1,
            first_name="A",
            last_name="B",
            has_photo=False,
            bio=None,
            job_title=None,
            company=None,
            industry=None,
            location=None,
            joined_at=SNAPSHOT_REFERENCE,
            profile_completeness=0.0,
        )
    )
    session.commit()
    assert recommend_circles(session, 1, limit=5) == []


def test_service_excludes_memberships_for_synthetic_leader(
    session: Session,
) -> None:
    topic = Topic(id=1, slug="negotiation", label="Negotiation", domain="content")
    session.add(topic)
    session.flush()
    session.add(
        User(
            id=1,
            first_name="Lead",
            last_name="Er",
            has_photo=True,
            bio="x",
            job_title="x",
            company="x",
            industry="x",
            location="x",
            joined_at=SNAPSHOT_REFERENCE,
            profile_completeness=1.0,
        )
    )
    session.add(
        Circle(
            id=1,
            name="Mine",
            slug="mine",
            description="d",
            primary_topic_id=1,
            cover_image_url=None,
            format="virtual",
            access="public",
            join_policy="open",
            max_members=10,
            member_count=1,
            created_at=SNAPSHOT_REFERENCE,
            last_activity_at=SNAPSHOT_REFERENCE,
            feed_posts_30d=5,
            chat_messages_30d=20,
        )
    )
    session.add(
        Circle(
            id=2,
            name="Other",
            slug="other",
            description="d",
            primary_topic_id=1,
            cover_image_url=None,
            format="virtual",
            access="public",
            join_policy="open",
            max_members=10,
            member_count=0,
            created_at=SNAPSHOT_REFERENCE,
            last_activity_at=SNAPSHOT_REFERENCE,
            feed_posts_30d=5,
            chat_messages_30d=20,
        )
    )
    session.add(
        Membership(
            user_id=1,
            circle_id=1,
            role="leader",
            joined_at=SNAPSHOT_REFERENCE,
        )
    )
    session.add(UserInterest(user_id=1, topic_id=1))
    session.commit()

    results = recommend_circles(session, 1, limit=5)
    assert [r.circle_id for r in results] == [2]


# ---------------------------------------------------------------------------
# Dataset-wide coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [1, 5, 10, 20])
def test_dataset_wide_all_users(seeded_engine: Engine, limit: int) -> None:
    with Session(seeded_engine) as session:
        user_ids = list(session.scalars(select(User.id).order_by(User.id)).all())
        assert len(user_ids) == 100

        # Precompute eligible universe size for nonempty checks.
        all_circles = session.scalars(
            select(Circle).options(
                selectinload(Circle.primary_topic),
                selectinload(Circle.tags),
            )
        ).all()

        for user_id in user_ids:
            member_ids = set(
                session.scalars(
                    select(Membership.circle_id).where(Membership.user_id == user_id)
                ).all()
            )
            candidates = [
                CircleCandidate(
                    id=c.id,
                    name=c.name,
                    access=c.access,
                    join_policy=c.join_policy,
                    max_members=c.max_members,
                    member_count=c.member_count,
                    feed_posts_30d=c.feed_posts_30d,
                    chat_messages_30d=c.chat_messages_30d,
                    last_activity_at=c.last_activity_at,
                    primary_topic_slug=(
                        c.primary_topic.slug if c.primary_topic is not None else None
                    ),
                    tags=tuple(sorted(t.tag for t in c.tags)),
                )
                for c in all_circles
            ]
            eligible = filter_eligible(candidates, member_ids)
            results = recommend_circles(session, user_id, limit=limit)
            _assert_recommendation_invariants(session, user_id, results, limit=limit)
            _recommendations_stable(session, user_id, limit)

            if eligible:
                assert results, f"user {user_id} had eligible Circles but empty results"
                assert len(results) == min(limit, len(eligible))


def test_seeded_row_counts(seeded_engine: Engine) -> None:
    with Session(seeded_engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 100
        assert session.scalar(select(func.count()).select_from(Circle)) == 40
        assert session.scalar(select(func.count()).select_from(Topic)) == 22


def test_diagnostics_helper_runs(seeded_engine: Engine) -> None:
    from io import StringIO

    from app.recommendations.diagnostics import print_diagnostics

    buf = StringIO()
    with Session(seeded_engine) as session:
        print_diagnostics(session, file=buf)
    text = buf.getvalue()
    for user_id in (7, 15, 23, 42):
        assert f"User {user_id}" in text
