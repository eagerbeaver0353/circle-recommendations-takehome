"""Seed correctness, idempotence, refresh, and failure/transaction tests."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from app.database import create_db_engine
from app.models import Activity, Circle, CircleTag, Membership, Topic, User, UserInterest
from app.seed import SeedValidationError, seed_database
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.conftest import read_json, write_json

EXPECTED_COUNTS = {
    "topics": 22,
    "users": 100,
    "circles": 40,
    "memberships": 441,
    "activity": 386,
}


def _counts(session: Session) -> dict[str, int]:
    return {
        "topics": session.scalar(select(func.count()).select_from(Topic)) or 0,
        "users": session.scalar(select(func.count()).select_from(User)) or 0,
        "circles": session.scalar(select(func.count()).select_from(Circle)) or 0,
        "user_interests": session.scalar(select(func.count()).select_from(UserInterest)) or 0,
        "circle_tags": session.scalar(select(func.count()).select_from(CircleTag)) or 0,
        "memberships": session.scalar(select(func.count()).select_from(Membership)) or 0,
        "activity": session.scalar(select(func.count()).select_from(Activity)) or 0,
    }


def test_seed_row_counts(seeded_engine: Engine, fixture_data_dir: Path) -> None:
    users = read_json(fixture_data_dir / "users.json")
    circles = read_json(fixture_data_dir / "circles.json")
    expected_interests = sum(len(u["topic_interests"]) for u in users)
    expected_tags = sum(len(set(c["tags"])) for c in circles)

    with Session(seeded_engine) as session:
        counts = _counts(session)

    assert counts["topics"] == EXPECTED_COUNTS["topics"]
    assert counts["users"] == EXPECTED_COUNTS["users"]
    assert counts["circles"] == EXPECTED_COUNTS["circles"]
    assert counts["memberships"] == EXPECTED_COUNTS["memberships"]
    assert counts["activity"] == EXPECTED_COUNTS["activity"]
    assert counts["user_interests"] == expected_interests
    assert counts["circle_tags"] == expected_tags


def test_seed_relationships_match_json(seeded_engine: Engine, fixture_data_dir: Path) -> None:
    topics = {t["slug"]: t for t in read_json(fixture_data_dir / "topics.json")}
    users = {u["id"]: u for u in read_json(fixture_data_dir / "users.json")}
    circles = {c["id"]: c for c in read_json(fixture_data_dir / "circles.json")}
    memberships = read_json(fixture_data_dir / "memberships.json")
    activity = read_json(fixture_data_dir / "activity.json")

    with Session(seeded_engine) as session:
        db_topics = {t.slug: t for t in session.scalars(select(Topic)).all()}
        assert set(db_topics) == set(topics)

        for user_id, src in users.items():
            db_user = session.get(User, user_id)
            assert db_user is not None
            assert db_user.first_name == src["first_name"]
            assert db_user.last_name == src["last_name"]
            assert db_user.has_photo is src["has_photo"]
            assert db_user.bio == src["bio"]
            assert db_user.job_title == src["job_title"]
            assert db_user.company == src["company"]
            assert db_user.industry == src["industry"]
            assert db_user.location == src["location"]
            assert float(db_user.profile_completeness) == float(src["profile_completeness"])
            interest_slugs = {
                interest.topic.slug for interest in db_user.user_interests
            }
            assert interest_slugs == set(src["topic_interests"])

        for circle_id, src in circles.items():
            db_circle = session.get(Circle, circle_id)
            assert db_circle is not None
            assert db_circle.name == src["name"]
            assert db_circle.slug == src["slug"]
            assert db_circle.description == src["description"]
            assert db_circle.cover_image_url == src["cover_image_url"]
            assert db_circle.format == src["format"]
            assert db_circle.access == src["access"]
            assert db_circle.join_policy == src["join_policy"]
            assert db_circle.max_members == src["max_members"]
            assert db_circle.member_count == src["member_count"]
            assert db_circle.feed_posts_30d == src["feed_posts_30d"]
            assert db_circle.chat_messages_30d == src["chat_messages_30d"]
            if src["topic"] is None:
                assert db_circle.primary_topic_id is None
            else:
                assert db_circle.primary_topic is not None
                assert db_circle.primary_topic.slug == src["topic"]
            assert {tag.tag for tag in db_circle.tags} == set(src["tags"])

        db_memberships = {
            (m.user_id, m.circle_id, m.role)
            for m in session.scalars(select(Membership)).all()
        }
        assert db_memberships == {
            (m["user_id"], m["circle_id"], m["role"]) for m in memberships
        }

        for post in activity:
            db_post = session.get(Activity, post["id"])
            assert db_post is not None
            assert db_post.circle_id == post["circle_id"]
            assert db_post.author_user_id == post["author_user_id"]
            assert db_post.body == post["body"]
            assert db_post.reaction_count == post["reaction_count"]
            assert db_post.comment_count == post["comment_count"]
            assert db_post.save_count == post["save_count"]


def test_membership_counts_agree_with_circle_aggregates(seeded_engine: Engine) -> None:
    with Session(seeded_engine) as session:
        for circle in session.scalars(select(Circle)).all():
            actual = session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.circle_id == circle.id)
            )
            assert actual == circle.member_count


def test_planted_records_retain_original_values(
    seeded_engine: Engine, fixture_data_dir: Path
) -> None:
    users = {u["id"]: u for u in read_json(fixture_data_dir / "users.json")}
    circles = {c["id"]: c for c in read_json(fixture_data_dir / "circles.json")}

    with Session(seeded_engine) as session:
        cold = session.get(User, 42)
        assert cold is not None
        assert cold.first_name == "Zoe"
        assert cold.last_name == "Ellis"
        assert cold.has_photo is False
        assert cold.bio is None
        assert cold.job_title is None
        assert cold.company is None
        assert cold.industry is None
        assert cold.location is None
        assert float(cold.profile_completeness) == 0.0
        assert cold.user_interests == []
        assert session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.user_id == 42)
        ) == 0
        assert users[42]["topic_interests"] == []

        obvious = session.get(User, 7)
        assert obvious is not None
        assert {i.topic.slug for i in obvious.user_interests} == {
            "leadership-skills",
            "public-speaking",
        }

        for circle_id in (10, 11, 12):
            circle = session.get(Circle, circle_id)
            assert circle is not None
            assert circle.primary_topic.slug == "negotiation"
            assert circle.primary_topic.slug == circles[circle_id]["topic"]

        full = session.get(Circle, 20)
        assert full is not None
        assert full.member_count == full.max_members == circles[20]["member_count"]
        assert full.max_members == circles[20]["max_members"]

        inactive = session.get(Circle, 21)
        assert inactive is not None
        assert inactive.feed_posts_30d == 0
        assert inactive.feed_posts_30d == circles[21]["feed_posts_30d"]


def test_nulls_and_empty_collections_import(seeded_engine: Engine) -> None:
    with Session(seeded_engine) as session:
        # Circles 27/28 have null topics and empty tags in the fixture.
        for circle_id in (27, 28):
            circle = session.get(Circle, circle_id)
            assert circle is not None
            assert circle.primary_topic_id is None
            assert circle.tags == []

        # User 42 has empty interests; several users have null profile fields.
        cold = session.get(User, 42)
        assert cold is not None
        assert cold.user_interests == []
        assert cold.bio is None

        uncapped = [
            c for c in session.scalars(select(Circle)).all() if c.max_members is None
        ]
        assert len(uncapped) >= 1


def test_seed_idempotent(tmp_db_url: str, fixture_data_dir: Path) -> None:
    first = seed_database(database_url=tmp_db_url, data_dir=fixture_data_dir)
    second = seed_database(database_url=tmp_db_url, data_dir=fixture_data_dir)
    assert first == second

    engine = create_db_engine(tmp_db_url)
    with Session(engine) as session:
        counts = _counts(session)
        interest_pairs = session.scalars(select(UserInterest)).all()
        membership_pairs = session.scalars(select(Membership)).all()
    engine.dispose()

    assert counts["topics"] == EXPECTED_COUNTS["topics"]
    assert counts["users"] == EXPECTED_COUNTS["users"]
    assert counts["circles"] == EXPECTED_COUNTS["circles"]
    assert counts["memberships"] == EXPECTED_COUNTS["memberships"]
    assert counts["activity"] == EXPECTED_COUNTS["activity"]
    assert len(interest_pairs) == len({(i.user_id, i.topic_id) for i in interest_pairs})
    assert len(membership_pairs) == len(
        {(m.user_id, m.circle_id) for m in membership_pairs}
    )


def test_changed_fixtures_refresh_consistently(
    tmp_db_url: str, mutable_fixture_dir: Path
) -> None:
    seed_database(database_url=tmp_db_url, data_dir=mutable_fixture_dir)

    topics_path = mutable_fixture_dir / "topics.json"
    topics = read_json(topics_path)
    topics.append(
        {
            "id": 999,
            "slug": "new-topic",
            "label": "New Topic",
            "domain": "content",
        }
    )
    write_json(topics_path, topics)

    users_path = mutable_fixture_dir / "users.json"
    users = read_json(users_path)
    users[0]["topic_interests"] = ["new-topic"]
    write_json(users_path, users)

    counts = seed_database(database_url=tmp_db_url, data_dir=mutable_fixture_dir)
    assert counts["topics"] == EXPECTED_COUNTS["topics"] + 1

    engine = create_db_engine(tmp_db_url)
    with Session(engine) as session:
        topic = session.scalar(select(Topic).where(Topic.slug == "new-topic"))
        assert topic is not None
        interests = session.scalars(
            select(UserInterest).where(UserInterest.user_id == users[0]["id"])
        ).all()
        assert len(interests) == 1
        assert interests[0].topic_id == topic.id
    engine.dispose()


def test_invalid_foreign_key_rejected(
    tmp_db_url: str, mutable_fixture_dir: Path
) -> None:
    memberships_path = mutable_fixture_dir / "memberships.json"
    memberships = read_json(memberships_path)
    memberships.append(
        {
            "user_id": 1,
            "circle_id": 99999,
            "role": "member",
            "joined_at": "2026-01-01T00:00:00.000Z",
        }
    )
    write_json(memberships_path, memberships)

    with pytest.raises(SeedValidationError, match="unknown circle_id"):
        seed_database(database_url=tmp_db_url, data_dir=mutable_fixture_dir)


def test_duplicate_memberships_rejected(
    tmp_db_url: str, mutable_fixture_dir: Path
) -> None:
    memberships_path = mutable_fixture_dir / "memberships.json"
    memberships = read_json(memberships_path)
    memberships.append(copy.deepcopy(memberships[0]))
    write_json(memberships_path, memberships)

    with pytest.raises(SeedValidationError, match="Duplicate membership"):
        seed_database(database_url=tmp_db_url, data_dir=mutable_fixture_dir)


def test_duplicate_user_interests_rejected(
    tmp_db_url: str, mutable_fixture_dir: Path
) -> None:
    users_path = mutable_fixture_dir / "users.json"
    users = read_json(users_path)
    target = next(u for u in users if u["topic_interests"])
    target["topic_interests"] = target["topic_interests"] + [target["topic_interests"][0]]
    write_json(users_path, users)

    with pytest.raises(SeedValidationError, match="duplicate topic_interests"):
        seed_database(database_url=tmp_db_url, data_dir=mutable_fixture_dir)


def test_invalid_source_does_not_partially_seed(
    tmp_db_url: str, mutable_fixture_dir: Path
) -> None:
    from app.database import init_db

    activity_path = mutable_fixture_dir / "activity.json"
    activity = read_json(activity_path)
    activity[0]["author_user_id"] = 99999
    write_json(activity_path, activity)

    with pytest.raises(SeedValidationError):
        seed_database(database_url=tmp_db_url, data_dir=mutable_fixture_dir)

    # Validation fails before import, so create an empty schema and confirm no rows.
    engine = create_db_engine(tmp_db_url)
    init_db(engine)
    with Session(engine) as session:
        assert _counts(session)["users"] == 0
        assert _counts(session)["activity"] == 0
    engine.dispose()


def test_failed_refresh_preserves_previous_dataset(
    tmp_db_url: str, mutable_fixture_dir: Path, fixture_data_dir: Path
) -> None:
    seed_database(database_url=tmp_db_url, data_dir=fixture_data_dir)

    engine = create_db_engine(tmp_db_url)
    with Session(engine) as session:
        before = _counts(session)
        cold_before = session.get(User, 42)
        assert cold_before is not None
        cold_name = cold_before.first_name
    engine.dispose()

    # Corrupt fixtures after a successful seed.
    users_path = mutable_fixture_dir / "users.json"
    users = read_json(users_path)
    users[0]["topic_interests"] = ["not-a-real-topic"]
    write_json(users_path, users)

    with pytest.raises(SeedValidationError, match="unknown topic slug"):
        seed_database(database_url=tmp_db_url, data_dir=mutable_fixture_dir)

    engine = create_db_engine(tmp_db_url)
    with Session(engine) as session:
        after = _counts(session)
        cold_after = session.get(User, 42)
        assert cold_after is not None
        assert after == before
        assert cold_after.first_name == cold_name
    engine.dispose()


def test_activity_author_must_belong_to_circle(
    tmp_db_url: str, mutable_fixture_dir: Path
) -> None:
    # Pick a user who is not a member of circle 1 and attribute a post to them.
    memberships = read_json(mutable_fixture_dir / "memberships.json")
    members_of_1 = {m["user_id"] for m in memberships if m["circle_id"] == 1}
    outsider = next(
        u["id"]
        for u in read_json(mutable_fixture_dir / "users.json")
        if u["id"] not in members_of_1
    )

    activity_path = mutable_fixture_dir / "activity.json"
    activity = read_json(activity_path)
    activity[0]["circle_id"] = 1
    activity[0]["author_user_id"] = outsider
    write_json(activity_path, activity)

    with pytest.raises(SeedValidationError, match="is not a member"):
        seed_database(database_url=tmp_db_url, data_dir=mutable_fixture_dir)
