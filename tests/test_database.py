"""Schema, relationship, index, and SQLite FK-enforcement tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.models import Activity, Circle, Membership, Topic, User, UserInterest
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

EXPECTED_TABLES = {
    "users",
    "topics",
    "circles",
    "user_interests",
    "circle_tags",
    "memberships",
    "activity",
}


def test_all_seven_tables_exist(engine: Engine) -> None:
    inspector = inspect(engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))


def test_primary_keys(engine: Engine) -> None:
    inspector = inspect(engine)

    assert inspector.get_pk_constraint("users")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("topics")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("circles")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("activity")["constrained_columns"] == ["id"]
    assert set(inspector.get_pk_constraint("user_interests")["constrained_columns"]) == {
        "user_id",
        "topic_id",
    }
    assert set(inspector.get_pk_constraint("circle_tags")["constrained_columns"]) == {
        "circle_id",
        "tag",
    }
    assert set(inspector.get_pk_constraint("memberships")["constrained_columns"]) == {
        "user_id",
        "circle_id",
    }


def test_foreign_keys(engine: Engine) -> None:
    inspector = inspect(engine)

    circle_fks = inspector.get_foreign_keys("circles")
    assert any(
        fk["referred_table"] == "topics" and fk["constrained_columns"] == ["primary_topic_id"]
        for fk in circle_fks
    )

    interest_fks = {
        (tuple(fk["constrained_columns"]), fk["referred_table"])
        for fk in inspector.get_foreign_keys("user_interests")
    }
    assert (("user_id",), "users") in interest_fks
    assert (("topic_id",), "topics") in interest_fks

    membership_fks = {
        (tuple(fk["constrained_columns"]), fk["referred_table"])
        for fk in inspector.get_foreign_keys("memberships")
    }
    assert (("user_id",), "users") in membership_fks
    assert (("circle_id",), "circles") in membership_fks

    activity_fks = {
        (tuple(fk["constrained_columns"]), fk["referred_table"])
        for fk in inspector.get_foreign_keys("activity")
    }
    assert (("circle_id",), "circles") in activity_fks
    assert (("author_user_id",), "users") in activity_fks


def test_unique_topic_slug(engine: Engine) -> None:
    inspector = inspect(engine)
    unique = inspector.get_unique_constraints("topics")
    assert any(uq["column_names"] == ["slug"] for uq in unique) or any(
        idx["unique"] and idx["column_names"] == ["slug"]
        for idx in inspector.get_indexes("topics")
    )


def test_relevant_indexes_exist(engine: Engine) -> None:
    inspector = inspect(engine)

    membership_indexes = inspector.get_indexes("memberships")
    assert any(idx["column_names"] == ["circle_id"] for idx in membership_indexes)

    circle_indexes = inspector.get_indexes("circles")
    assert any(idx["column_names"] == ["primary_topic_id"] for idx in circle_indexes)

    activity_indexes = inspector.get_indexes("activity")
    assert any(
        idx["column_names"] == ["circle_id", "created_at"] for idx in activity_indexes
    )


def test_sqlite_enforces_foreign_keys(engine: Engine, session: Session) -> None:
    with engine.connect() as conn:
        enabled = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert enabled == 1

    now = datetime(2026, 1, 1, tzinfo=UTC)
    session.add(
        User(
            id=1,
            first_name="A",
            last_name="B",
            has_photo=False,
            joined_at=now,
            profile_completeness=0.0,
        )
    )
    session.commit()

    session.add(
        Membership(
            user_id=1,
            circle_id=999,
            role="member",
            joined_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_nullable_topic_and_capacity(session: Session) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    session.add(
        Circle(
            id=1,
            name="Open Circle",
            slug="open-circle",
            description=None,
            primary_topic_id=None,
            cover_image_url=None,
            format="virtual",
            access="public",
            join_policy="open",
            max_members=None,
            member_count=0,
            created_at=now,
            last_activity_at=now,
            feed_posts_30d=0,
            chat_messages_30d=0,
        )
    )
    session.commit()

    circle = session.get(Circle, 1)
    assert circle is not None
    assert circle.primary_topic_id is None
    assert circle.max_members is None
    assert circle.description is None


def test_relationships_round_trip(session: Session) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    topic = Topic(id=1, slug="negotiation", label="Negotiation", domain="content")
    user = User(
        id=1,
        first_name="Priya",
        last_name="Sharma",
        has_photo=True,
        joined_at=now,
        profile_completeness=1.0,
    )
    circle = Circle(
        id=1,
        name="Negotiation Circle",
        slug="negotiation-circle",
        description="desc",
        primary_topic_id=1,
        cover_image_url=None,
        format="hybrid",
        access="public",
        join_policy="open",
        max_members=10,
        member_count=1,
        created_at=now,
        last_activity_at=now,
        feed_posts_30d=1,
        chat_messages_30d=2,
    )
    session.add_all([topic, user, circle])
    session.flush()
    session.add(UserInterest(user_id=1, topic_id=1))
    session.add(
        Membership(user_id=1, circle_id=1, role="leader", joined_at=now)
    )
    session.add(
        Activity(
            id=1,
            circle_id=1,
            author_user_id=1,
            body="hello",
            reaction_count=0,
            comment_count=0,
            save_count=0,
            created_at=now,
        )
    )
    session.commit()

    loaded_user = session.get(User, 1)
    assert loaded_user is not None
    assert len(loaded_user.memberships) == 1
    assert loaded_user.memberships[0].circle.name == "Negotiation Circle"
    assert session.scalar(select(UserInterest).where(UserInterest.user_id == 1)) is not None
    assert session.get(Circle, 1).primary_topic.slug == "negotiation"


def test_utc_datetimes_round_trip_aware(session: Session) -> None:
    now = datetime(2026, 9, 21, 12, 30, 0, tzinfo=UTC)
    session.add(
        User(
            id=1,
            first_name="A",
            last_name="B",
            has_photo=False,
            joined_at=now,
            profile_completeness=0.0,
        )
    )
    session.commit()
    session.expire_all()

    user = session.get(User, 1)
    assert user is not None
    assert user.joined_at.tzinfo is not None
    assert user.joined_at == now


def test_nonnegative_activity_constraint(session: Session) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    session.add(
        User(
            id=1,
            first_name="A",
            last_name="B",
            has_photo=False,
            joined_at=now,
            profile_completeness=0.0,
        )
    )
    session.add(
        Circle(
            id=1,
            name="C",
            slug="c",
            description=None,
            primary_topic_id=None,
            cover_image_url=None,
            format="virtual",
            access="public",
            join_policy="open",
            max_members=None,
            member_count=0,
            created_at=now,
            last_activity_at=now,
            feed_posts_30d=0,
            chat_messages_30d=0,
        )
    )
    session.commit()

    session.add(
        Activity(
            id=1,
            circle_id=1,
            author_user_id=1,
            body="x",
            reaction_count=-1,
            comment_count=0,
            save_count=0,
            created_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
