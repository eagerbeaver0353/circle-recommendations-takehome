"""Idempotent seed command: ``python -m app.seed``.

Loads the committed JSON fixtures under ``data/``, validates them, then
transactionally replaces seed-managed rows. A failed validation or import
leaves any previous valid database contents unchanged.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database import create_db_engine, init_db
from app.models import Activity, Circle, CircleTag, Membership, Topic, User, UserInterest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"

FORMATS = frozenset({"in_person", "virtual", "hybrid"})
ACCESS_VALUES = frozenset({"public", "unlisted"})
JOIN_POLICIES = frozenset({"open", "request"})
ROLES = frozenset({"member", "leader"})

# Seed-managed tables, deleted in FK-safe order before re-import.
SEED_TABLES = (Activity, Membership, CircleTag, UserInterest, Circle, User, Topic)


class SeedValidationError(ValueError):
    """Raised when fixture data fails integrity checks."""


def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware UTC datetime."""
    if not isinstance(value, str) or not value:
        raise SeedValidationError(f"Expected ISO datetime string, got {value!r}")
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SeedValidationError(f"Invalid ISO datetime: {value!r}") from exc
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def load_json(path: Path) -> list[dict[str, Any]]:
    """Load a JSON array fixture file."""
    if not path.is_file():
        raise SeedValidationError(f"Missing fixture file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeedValidationError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise SeedValidationError(f"Expected a JSON array in {path}")
    return payload


def _require_keys(record: dict[str, Any], keys: set[str], label: str) -> None:
    missing = keys - set(record)
    if missing:
        raise SeedValidationError(f"{label} missing required fields: {sorted(missing)}")


def _unique_ids(records: list[dict[str, Any]], key: str, label: str) -> set[Any]:
    ids = [record.get(key) for record in records]
    if any(i is None for i in ids):
        raise SeedValidationError(f"{label} contains a null {key}")
    counts = Counter(ids)
    dupes = sorted(i for i, n in counts.items() if n > 1)
    if dupes:
        raise SeedValidationError(f"{label} has duplicate {key} values: {dupes[:10]}")
    return set(ids)


def validate_fixtures(
    topics: list[dict[str, Any]],
    users: list[dict[str, Any]],
    circles: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
    activity: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate fixture integrity before any database writes.

    Returns derived lookup maps used by the importer.
    """
    topic_ids = _unique_ids(topics, "id", "topics")
    topic_slugs: dict[str, int] = {}
    for topic in topics:
        _require_keys(topic, {"id", "slug", "label", "domain"}, f"topic {topic.get('id')}")
        slug = topic["slug"]
        if not isinstance(slug, str) or not slug:
            raise SeedValidationError(f"topic {topic['id']} has invalid slug")
        if slug in topic_slugs:
            raise SeedValidationError(f"Duplicate topic slug: {slug}")
        if not isinstance(topic["label"], str) or not topic["label"]:
            raise SeedValidationError(f"topic {topic['id']} has invalid label")
        if not isinstance(topic["domain"], str) or not topic["domain"]:
            raise SeedValidationError(f"topic {topic['id']} has invalid domain")
        topic_slugs[slug] = topic["id"]

    user_ids = _unique_ids(users, "id", "users")
    for user in users:
        _require_keys(
            user,
            {
                "id",
                "first_name",
                "last_name",
                "has_photo",
                "bio",
                "job_title",
                "company",
                "industry",
                "location",
                "joined_at",
                "topic_interests",
                "profile_completeness",
            },
            f"user {user.get('id')}",
        )
        if not isinstance(user["first_name"], str) or not user["first_name"]:
            raise SeedValidationError(f"user {user['id']} missing first_name")
        if not isinstance(user["last_name"], str) or not user["last_name"]:
            raise SeedValidationError(f"user {user['id']} missing last_name")
        if not isinstance(user["has_photo"], bool):
            raise SeedValidationError(f"user {user['id']} has_photo must be bool")
        completeness = user["profile_completeness"]
        if not isinstance(completeness, (int, float)) or not (0 <= completeness <= 1):
            raise SeedValidationError(
                f"user {user['id']} profile_completeness out of range: {completeness!r}"
            )
        parse_utc(user["joined_at"])
        interests = user["topic_interests"]
        if not isinstance(interests, list):
            raise SeedValidationError(f"user {user['id']} topic_interests must be a list")
        if len(interests) != len(set(interests)):
            raise SeedValidationError(f"user {user['id']} has duplicate topic_interests")
        for slug in interests:
            if slug not in topic_slugs:
                raise SeedValidationError(
                    f"user {user['id']} references unknown topic slug {slug!r}"
                )

    circle_ids = _unique_ids(circles, "id", "circles")
    for circle in circles:
        _require_keys(
            circle,
            {
                "id",
                "name",
                "slug",
                "description",
                "topic",
                "tags",
                "cover_image_url",
                "format",
                "access",
                "join_policy",
                "max_members",
                "member_count",
                "created_at",
                "last_activity_at",
                "feed_posts_30d",
                "chat_messages_30d",
            },
            f"circle {circle.get('id')}",
        )
        if not isinstance(circle["name"], str) or not circle["name"]:
            raise SeedValidationError(f"circle {circle['id']} missing name")
        if not isinstance(circle["slug"], str) or not circle["slug"]:
            raise SeedValidationError(f"circle {circle['id']} missing slug")
        topic_slug = circle["topic"]
        if topic_slug is not None and topic_slug not in topic_slugs:
            raise SeedValidationError(
                f"circle {circle['id']} references unknown topic {topic_slug!r}"
            )
        tags = circle["tags"]
        if not isinstance(tags, list):
            raise SeedValidationError(f"circle {circle['id']} tags must be a list")
        # Source fixtures may repeat a tag; the composite PK stores the unique set.
        for tag in tags:
            if not isinstance(tag, str) or not tag:
                raise SeedValidationError(f"circle {circle['id']} has invalid tag {tag!r}")
        if circle["format"] not in FORMATS:
            raise SeedValidationError(
                f"circle {circle['id']} has unsupported format {circle['format']!r}"
            )
        if circle["access"] not in ACCESS_VALUES:
            raise SeedValidationError(
                f"circle {circle['id']} has unsupported access {circle['access']!r}"
            )
        if circle["join_policy"] not in JOIN_POLICIES:
            raise SeedValidationError(
                f"circle {circle['id']} has unsupported join_policy {circle['join_policy']!r}"
            )
        max_members = circle["max_members"]
        if max_members is not None and (
            not isinstance(max_members, int) or max_members < 0
        ):
            raise SeedValidationError(
                f"circle {circle['id']} max_members must be null or nonnegative int"
            )
        member_count = circle["member_count"]
        if not isinstance(member_count, int) or member_count < 0:
            raise SeedValidationError(
                f"circle {circle['id']} member_count must be a nonnegative int"
            )
        for field in ("feed_posts_30d", "chat_messages_30d"):
            value = circle[field]
            if not isinstance(value, int) or value < 0:
                raise SeedValidationError(
                    f"circle {circle['id']} {field} must be a nonnegative int"
                )
        parse_utc(circle["created_at"])
        parse_utc(circle["last_activity_at"])

    membership_keys: set[tuple[int, int]] = set()
    membership_counts: Counter[int] = Counter()
    for membership in memberships:
        _require_keys(
            membership,
            {"user_id", "circle_id", "role", "joined_at"},
            "membership",
        )
        user_id = membership["user_id"]
        circle_id = membership["circle_id"]
        if user_id not in user_ids:
            raise SeedValidationError(
                f"membership references unknown user_id={user_id}"
            )
        if circle_id not in circle_ids:
            raise SeedValidationError(
                f"membership references unknown circle_id={circle_id}"
            )
        key = (user_id, circle_id)
        if key in membership_keys:
            raise SeedValidationError(f"Duplicate membership for user={user_id} circle={circle_id}")
        membership_keys.add(key)
        if membership["role"] not in ROLES:
            raise SeedValidationError(
                f"membership user={user_id} circle={circle_id} has invalid role "
                f"{membership['role']!r}"
            )
        parse_utc(membership["joined_at"])
        membership_counts[circle_id] += 1

    for circle in circles:
        expected = circle["member_count"]
        actual = membership_counts[circle["id"]]
        if expected != actual:
            raise SeedValidationError(
                f"circle {circle['id']} member_count={expected} but found {actual} memberships"
            )

    activity_ids = _unique_ids(activity, "id", "activity")
    for post in activity:
        _require_keys(
            post,
            {
                "id",
                "circle_id",
                "author_user_id",
                "body",
                "reaction_count",
                "comment_count",
                "save_count",
                "created_at",
            },
            f"activity {post.get('id')}",
        )
        if post["circle_id"] not in circle_ids:
            raise SeedValidationError(
                f"activity {post['id']} references unknown circle_id={post['circle_id']}"
            )
        if post["author_user_id"] not in user_ids:
            raise SeedValidationError(
                f"activity {post['id']} references unknown author_user_id={post['author_user_id']}"
            )
        if (post["author_user_id"], post["circle_id"]) not in membership_keys:
            raise SeedValidationError(
                f"activity {post['id']} author {post['author_user_id']} "
                f"is not a member of circle {post['circle_id']}"
            )
        if not isinstance(post["body"], str) or not post["body"]:
            raise SeedValidationError(f"activity {post['id']} missing body")
        for field in ("reaction_count", "comment_count", "save_count"):
            value = post[field]
            if not isinstance(value, int) or value < 0:
                raise SeedValidationError(
                    f"activity {post['id']} {field} must be a nonnegative int"
                )
        parse_utc(post["created_at"])

    return {
        "topic_ids": topic_ids,
        "topic_slugs": topic_slugs,
        "user_ids": user_ids,
        "circle_ids": circle_ids,
        "membership_keys": membership_keys,
        "activity_ids": activity_ids,
    }


def _clear_seed_tables(session: Session) -> None:
    """Delete seed-managed rows in FK-safe order within the current transaction."""
    for table in SEED_TABLES:
        session.execute(delete(table))


def import_fixtures(
    session: Session,
    topics: list[dict[str, Any]],
    users: list[dict[str, Any]],
    circles: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
    activity: list[dict[str, Any]],
    *,
    topic_slugs: dict[str, int],
) -> None:
    """Write validated fixtures into *session* (caller owns the transaction)."""
    _clear_seed_tables(session)

    session.add_all(
        [
            Topic(
                id=topic["id"],
                slug=topic["slug"],
                label=topic["label"],
                domain=topic["domain"],
            )
            for topic in topics
        ]
    )
    session.flush()

    session.add_all(
        [
            User(
                id=user["id"],
                first_name=user["first_name"],
                last_name=user["last_name"],
                has_photo=user["has_photo"],
                bio=user["bio"],
                job_title=user["job_title"],
                company=user["company"],
                industry=user["industry"],
                location=user["location"],
                joined_at=parse_utc(user["joined_at"]),
                profile_completeness=float(user["profile_completeness"]),
            )
            for user in users
        ]
    )
    session.flush()

    interest_rows: list[UserInterest] = []
    for user in users:
        for slug in user["topic_interests"]:
            interest_rows.append(
                UserInterest(user_id=user["id"], topic_id=topic_slugs[slug])
            )
    session.add_all(interest_rows)

    session.add_all(
        [
            Circle(
                id=circle["id"],
                name=circle["name"],
                slug=circle["slug"],
                description=circle["description"],
                primary_topic_id=(
                    topic_slugs[circle["topic"]] if circle["topic"] is not None else None
                ),
                cover_image_url=circle["cover_image_url"],
                format=circle["format"],
                access=circle["access"],
                join_policy=circle["join_policy"],
                max_members=circle["max_members"],
                member_count=circle["member_count"],
                created_at=parse_utc(circle["created_at"]),
                last_activity_at=parse_utc(circle["last_activity_at"]),
                feed_posts_30d=circle["feed_posts_30d"],
                chat_messages_30d=circle["chat_messages_30d"],
            )
            for circle in circles
        ]
    )
    session.flush()

    tag_rows: list[CircleTag] = []
    for circle in circles:
        # Deduplicate while preserving first-seen order from the fixture.
        seen: set[str] = set()
        for tag in circle["tags"]:
            if tag in seen:
                continue
            seen.add(tag)
            tag_rows.append(CircleTag(circle_id=circle["id"], tag=tag))
    session.add_all(tag_rows)

    session.add_all(
        [
            Membership(
                user_id=membership["user_id"],
                circle_id=membership["circle_id"],
                role=membership["role"],
                joined_at=parse_utc(membership["joined_at"]),
            )
            for membership in memberships
        ]
    )

    session.add_all(
        [
            Activity(
                id=post["id"],
                circle_id=post["circle_id"],
                author_user_id=post["author_user_id"],
                body=post["body"],
                reaction_count=post["reaction_count"],
                comment_count=post["comment_count"],
                save_count=post["save_count"],
                created_at=parse_utc(post["created_at"]),
            )
            for post in activity
        ]
    )


def seed_database(
    *,
    database_url: str | None = None,
    data_dir: Path | None = None,
) -> dict[str, int]:
    """Validate fixtures and transactionally replace seed-managed database rows.

    Returns a mapping of table name → row count after a successful import.
    """
    directory = data_dir or DEFAULT_DATA_DIR
    topics = load_json(directory / "topics.json")
    users = load_json(directory / "users.json")
    circles = load_json(directory / "circles.json")
    memberships = load_json(directory / "memberships.json")
    activity = load_json(directory / "activity.json")

    # Validate fully before touching the database so bad fixtures never wipe data.
    derived = validate_fixtures(topics, users, circles, memberships, activity)

    engine = create_db_engine(database_url)
    init_db(engine)

    with Session(engine) as session:
        try:
            with session.begin():
                import_fixtures(
                    session,
                    topics,
                    users,
                    circles,
                    memberships,
                    activity,
                    topic_slugs=derived["topic_slugs"],
                )
            counts = {
                "topics": session.scalar(select(func.count()).select_from(Topic)) or 0,
                "users": session.scalar(select(func.count()).select_from(User)) or 0,
                "circles": session.scalar(select(func.count()).select_from(Circle)) or 0,
                "user_interests": (
                    session.scalar(select(func.count()).select_from(UserInterest)) or 0
                ),
                "circle_tags": (
                    session.scalar(select(func.count()).select_from(CircleTag)) or 0
                ),
                "memberships": (
                    session.scalar(select(func.count()).select_from(Membership)) or 0
                ),
                "activity": session.scalar(select(func.count()).select_from(Activity)) or 0,
            }
        except Exception:
            session.rollback()
            raise

    return counts


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python -m app.seed``."""
    del argv  # reserved for future flags; currently unused
    try:
        counts = seed_database()
    except SeedValidationError as exc:
        print(f"Seed validation failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - surface unexpected import errors clearly
        print(f"Seed import failed: {exc}", file=sys.stderr)
        return 1

    print("Seed completed successfully.")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
