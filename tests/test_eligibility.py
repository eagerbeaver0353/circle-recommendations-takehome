"""Unit tests for ADR 003 eligibility filtering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.recommendations.constants import SNAPSHOT_REFERENCE
from app.recommendations.eligibility import (
    filter_eligible,
    is_at_capacity,
    is_dormant,
    is_eligible,
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
        feed_posts_30d=5,
        chat_messages_30d=50,
        last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=2),
        primary_topic_slug="negotiation",
        tags=("negotiation",),
    )
    base.update(overrides)
    return CircleCandidate(**base)


def test_existing_member_excluded() -> None:
    circle = _circle(id=10)
    assert not is_eligible(circle, {10, 20})


def test_existing_leader_excluded() -> None:
    # Roles are not distinguished at eligibility time — any membership excludes.
    circle = _circle(id=7)
    assert not is_eligible(circle, member_circle_ids={7})


def test_full_circle_excluded() -> None:
    circle = _circle(max_members=15, member_count=15)
    assert is_at_capacity(15, 15)
    assert not is_eligible(circle, member_circle_ids=set())


def test_uncapped_circle_remains_eligible() -> None:
    circle = _circle(max_members=None, member_count=500)
    assert not is_at_capacity(None, 500)
    assert is_eligible(circle, member_circle_ids=set())


def test_public_open_circle_eligible() -> None:
    circle = _circle(access="public", join_policy="open")
    assert is_eligible(circle, member_circle_ids=set())


def test_public_request_to_join_remains_eligible() -> None:
    circle = _circle(access="public", join_policy="request")
    assert is_eligible(circle, member_circle_ids=set())


def test_unlisted_circle_excluded() -> None:
    circle = _circle(access="unlisted")
    assert not is_eligible(circle, member_circle_ids=set())


def test_clearly_dormant_circle_excluded() -> None:
    circle = _circle(
        feed_posts_30d=0,
        chat_messages_30d=3,
        last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=61),
    )
    assert is_dormant(
        feed_posts_30d=0,
        chat_messages_30d=3,
        last_activity_at=circle.last_activity_at,
    )
    assert not is_eligible(circle, member_circle_ids=set())


def test_moderately_active_circle_remains_eligible() -> None:
    # Feed posts present → not dormant even if last_activity is old.
    circle = _circle(
        feed_posts_30d=1,
        chat_messages_30d=0,
        last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=120),
    )
    assert is_eligible(circle, member_circle_ids=set())


def test_chat_above_dormancy_threshold_keeps_eligible() -> None:
    circle = _circle(
        feed_posts_30d=0,
        chat_messages_30d=4,
        last_activity_at=SNAPSHOT_REFERENCE - timedelta(days=100),
    )
    assert is_eligible(circle, member_circle_ids=set())


def test_missing_topic_tags_description_do_not_exclude() -> None:
    circle = _circle(primary_topic_slug=None, tags=())
    assert is_eligible(circle, member_circle_ids=set())


def test_exactly_60_days_inactive_is_not_dormant() -> None:
    last = SNAPSHOT_REFERENCE - timedelta(days=60)
    assert not is_dormant(
        feed_posts_30d=0,
        chat_messages_30d=0,
        last_activity_at=last,
    )
    circle = _circle(
        feed_posts_30d=0,
        chat_messages_30d=0,
        last_activity_at=last,
    )
    assert is_eligible(circle, member_circle_ids=set())


def test_filter_eligible_is_deterministic_and_non_mutating() -> None:
    circles = [
        _circle(id=3, access="unlisted"),
        _circle(id=1, access="public"),
        _circle(id=2, max_members=1, member_count=1),
    ]
    original_ids = [c.id for c in circles]
    result = filter_eligible(circles, member_circle_ids=set())
    assert [c.id for c in result] == [1]
    assert [c.id for c in circles] == original_ids


def test_dormancy_uses_snapshot_not_wall_clock() -> None:
    # Activity "yesterday" relative to a custom snapshot far in the past
    # would look ancient by wall clock but must use the snapshot.
    custom_snap = datetime(2020, 1, 1, tzinfo=UTC)
    last = custom_snap - timedelta(days=30)
    assert not is_dormant(
        feed_posts_30d=0,
        chat_messages_30d=0,
        last_activity_at=last,
        snapshot_reference=custom_snap,
    )
