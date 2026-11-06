"""FastAPI integration tests for Circle recommendations (ADR 006)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.database import create_db_engine, init_db
from app.main import create_app
from app.models import Circle, Membership, User
from app.recommendations.constants import SNAPSHOT_REFERENCE
from app.recommendations.eligibility import is_dormant
from app.recommendations.service import recommend_circles
from app.schemas import CircleRecommendationsResponse
from app.seed import seed_database
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session, selectinload

FORBIDDEN_JSON_KEYS = {
    "base_score",
    "adjusted_score",
    "evidence",
    "relevance_score",
    "relevance_weight",
    "quality_weight",
    "quality_score",
    "feed_quality",
    "chat_quality",
    "recency_quality",
    "personalization_mode",
    "relevance_source",
    "matched_topic_or_tag",
    "relevance_is_inferred",
}


@pytest.fixture
def api_app(tmp_db_url: str, fixture_data_dir: Path) -> Iterator[FastAPI]:
    """Seeded FastAPI application whose engine is bound to a temp database."""
    seed_database(database_url=tmp_db_url, data_dir=fixture_data_dir)
    application = create_app(database_url=tmp_db_url)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def api_client(api_app: FastAPI) -> Iterator[TestClient]:
    """Test client bound to an isolated, seeded temporary SQLite database."""
    with TestClient(api_app) as client:
        yield client


def _recommendations_url(user_id: int | str, *, limit: int | str | None = None) -> str:
    path = f"/api/v1/users/{user_id}/circle-recommendations"
    if limit is None:
        return path
    return f"{path}?limit={limit}"


def _assert_no_internal_fields(payload: object) -> None:
    if isinstance(payload, dict):
        assert FORBIDDEN_JSON_KEYS.isdisjoint(payload.keys())
        for value in payload.values():
            _assert_no_internal_fields(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_internal_fields(item)


def _assert_card_matches_circle(card: dict, circle: Circle) -> None:
    topic_slug = circle.primary_topic.slug if circle.primary_topic is not None else None
    assert card["circle_id"] == circle.id
    assert card["slug"] == circle.slug
    assert card["name"] == circle.name
    assert card["description"] == circle.description
    assert card["topic"] == topic_slug
    assert card["format"] == circle.format
    assert card["join_policy"] == circle.join_policy
    assert card["cover_image_url"] == circle.cover_image_url
    assert isinstance(card["reason"], str) and card["reason"].strip()
    # No raw kebab-case topic slugs as whole words in the explanation.
    for token in card["reason"].replace(".", " ").split():
        assert not (token.count("-") >= 1 and token.replace("-", "").isalpha())


def _normalize_sql(statement: str) -> str:
    """Collapse whitespace and lowercase SQL for robust substring checks."""
    return re.sub(r"\s+", " ", statement).strip().lower()


# ---------------------------------------------------------------------------
# HTTP functionality
# ---------------------------------------------------------------------------


def test_valid_request_returns_200(api_client: TestClient) -> None:
    response = api_client.get(_recommendations_url(7))
    assert response.status_code == 200
    body = response.json()
    CircleRecommendationsResponse.model_validate(body)
    _assert_no_internal_fields(body)


def test_default_limit_is_five(api_client: TestClient) -> None:
    response = api_client.get(_recommendations_url(7))
    assert response.status_code == 200
    assert len(response.json()["recommendations"]) == 5


@pytest.mark.parametrize("limit", [1, 5, 10, 20])
def test_limit_bounds_return_expected_sizes(api_client: TestClient, limit: int) -> None:
    response = api_client.get(_recommendations_url(7, limit=limit))
    assert response.status_code == 200
    recommendations = response.json()["recommendations"]
    assert 1 <= len(recommendations) <= limit
    if limit == 1:
        assert len(recommendations) == 1


@pytest.mark.parametrize("limit", [0, 21, -1, "invalid"])
def test_invalid_limits_return_422(api_client: TestClient, limit: int | str) -> None:
    response = api_client.get(_recommendations_url(7, limit=limit))
    assert response.status_code == 422


@pytest.mark.parametrize("user_id", [0, -1, "abc"])
def test_invalid_user_ids_return_422(api_client: TestClient, user_id: int | str) -> None:
    response = api_client.get(_recommendations_url(user_id))
    assert response.status_code == 422


def test_unknown_user_returns_404(api_client: TestClient) -> None:
    response = api_client.get(_recommendations_url(999_999))
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_user_with_zero_eligible_circles_returns_empty_array(api_app: FastAPI) -> None:
    """Construct a member of every eligible Circle, then expect an empty list."""
    with Session(api_app.state.engine) as session:
        assert session.get(User, 1) is not None
        circles = session.scalars(
            select(Circle).options(selectinload(Circle.primary_topic))
        ).all()
        existing = set(
            session.scalars(
                select(Membership.circle_id).where(Membership.user_id == 1)
            ).all()
        )
        for circle in circles:
            if circle.access != "public":
                continue
            if (
                circle.max_members is not None
                and circle.member_count >= circle.max_members
            ):
                continue
            if is_dormant(
                feed_posts_30d=circle.feed_posts_30d,
                chat_messages_30d=circle.chat_messages_30d,
                last_activity_at=circle.last_activity_at,
            ):
                continue
            if circle.id in existing:
                continue
            session.add(
                Membership(
                    user_id=1,
                    circle_id=circle.id,
                    role="member",
                    joined_at=SNAPSHOT_REFERENCE,
                )
            )
        session.commit()

    with TestClient(api_app) as client:
        response = client.get(_recommendations_url(1))
        assert response.status_code == 200
        body = response.json()
        assert body == {"user_id": 1, "recommendations": []}


def test_health_docs_and_openapi(api_client: TestClient) -> None:
    health = api_client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "database": "ready"}

    docs = api_client.get("/docs")
    assert docs.status_code == 200

    openapi = api_client.get("/openapi.json")
    assert openapi.status_code == 200
    schema = openapi.json()
    assert "/api/v1/users/{user_id}/circle-recommendations" in schema["paths"]
    assert "/health" in schema["paths"]


def test_health_returns_503_on_uninitialized_database(tmp_path: Path) -> None:
    """Fresh SQLite file without schema must not report ready."""
    db_url = f"sqlite:///{tmp_path / 'uninitialized.db'}"
    # Touch an empty SQLite file via the engine without creating tables.
    engine = create_db_engine(db_url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        conn.commit()
    engine.dispose()

    application = create_app(database_url=db_url)
    try:
        with TestClient(application) as client:
            response = client.get("/health")
            assert response.status_code == 503
            assert response.json() == {"detail": "Database is not ready"}
    finally:
        application.state.engine.dispose()


def test_health_returns_503_on_schema_only_database(tmp_path: Path) -> None:
    """Complete schema without seed data must not report ready."""
    db_url = f"sqlite:///{tmp_path / 'schema_only.db'}"
    engine = create_db_engine(db_url)
    try:
        init_db(engine)
    finally:
        engine.dispose()

    application = create_app(database_url=db_url)
    try:
        with TestClient(application) as client:
            response = client.get("/health")
            assert response.status_code == 503
            assert response.json() == {"detail": "Database is not ready"}
    finally:
        application.state.engine.dispose()


# ---------------------------------------------------------------------------
# Application isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("construct_order", ["a_then_b", "b_then_a"])
def test_apps_use_independent_databases(
    tmp_path: Path,
    fixture_data_dir: Path,
    construct_order: str,
) -> None:
    """Two create_app instances must keep distinct engines after both exist."""
    db_a = f"sqlite:///{tmp_path / 'iso_a.db'}"
    db_b = f"sqlite:///{tmp_path / 'iso_b.db'}"

    seed_database(database_url=db_a, data_dir=fixture_data_dir)

    # Database B: schema only, plus a single user that does not exist in A.
    engine_b_setup = create_db_engine(db_b)
    try:
        init_db(engine_b_setup)
        with Session(engine_b_setup) as session:
            session.add(
                User(
                    id=9001,
                    first_name="Iso",
                    last_name="Only",
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
    finally:
        engine_b_setup.dispose()

    if construct_order == "a_then_b":
        app_a = create_app(database_url=db_a)
        app_b = create_app(database_url=db_b)
    else:
        app_b = create_app(database_url=db_b)
        app_a = create_app(database_url=db_a)

    try:
        assert app_a.state.engine is not app_b.state.engine
        with (
            TestClient(app_a) as client_a,
            TestClient(app_b) as client_b,
        ):
            # A still serves the seeded assessment dataset.
            response_a = client_a.get(_recommendations_url(7, limit=1))
            assert response_a.status_code == 200
            assert response_a.json()["user_id"] == 7
            assert response_a.json()["recommendations"]

            # B does not have user 7, but does have the custom user.
            assert client_b.get(_recommendations_url(7)).status_code == 404
            response_b = client_b.get(_recommendations_url(9001))
            assert response_b.status_code == 200
            assert response_b.json() == {
                "user_id": 9001,
                "recommendations": [],
            }

            # Cross-check: A still does not know about B's custom user.
            assert client_a.get(_recommendations_url(9001)).status_code == 404
    finally:
        app_a.state.engine.dispose()
        app_b.state.engine.dispose()


# ---------------------------------------------------------------------------
# Response contract
# ---------------------------------------------------------------------------


def test_response_contract_and_ordering(api_app: FastAPI, api_client: TestClient) -> None:
    response = api_client.get(_recommendations_url(15, limit=5))
    assert response.status_code == 200
    body = response.json()
    parsed = CircleRecommendationsResponse.model_validate(body)
    _assert_no_internal_fields(body)

    assert parsed.user_id == 15
    assert parsed.recommendations
    ranks = [card.rank for card in parsed.recommendations]
    assert ranks == list(range(1, len(ranks) + 1))
    circle_ids = [card.circle_id for card in parsed.recommendations]
    assert len(circle_ids) == len(set(circle_ids))

    with Session(api_app.state.engine) as session:
        service_order = [
            rec.circle_id for rec in recommend_circles(session, 15, limit=5)
        ]
        assert circle_ids == service_order

        circles = {
            c.id: c
            for c in session.scalars(
                select(Circle).options(selectinload(Circle.primary_topic))
            ).all()
        }
        for card in body["recommendations"]:
            _assert_card_matches_circle(card, circles[card["circle_id"]])


def test_null_optional_fields_preserved(api_client: TestClient) -> None:
    """Circle 27 has null topic/description; cold-start user 42 often ranks it."""
    response = api_client.get(_recommendations_url(42, limit=5))
    assert response.status_code == 200
    cards = response.json()["recommendations"]
    assert cards
    null_topic_cards = [c for c in cards if c["circle_id"] == 27]
    if null_topic_cards:
        card = null_topic_cards[0]
        assert card["topic"] is None
        assert card["description"] is None
        assert card["reason"]


# ---------------------------------------------------------------------------
# Database efficiency
# ---------------------------------------------------------------------------


def test_selected_circle_metadata_uses_batched_query(api_app: FastAPI) -> None:
    engine = api_app.state.engine
    statements: list[str] = []

    def before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ) -> None:  # noqa: ANN001, ARG001
        statements.append(str(statement))

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        with TestClient(api_app) as client:
            response = client.get(_recommendations_url(7, limit=5))
            assert response.status_code == 200
            assert len(response.json()["recommendations"]) == 5
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)

    normalized = [_normalize_sql(sql) for sql in statements]
    recommendation_count = 5

    # Selected Circle metadata must be fetched through an IN batch.
    circle_batch_queries = [
        sql
        for sql in normalized
        if "from circles" in sql and re.search(r"\bcircles\.id in\b", sql)
    ]
    assert len(circle_batch_queries) >= 1

    # Metadata query count must not grow one-for-one with recommendation count.
    assert len(circle_batch_queries) < recommendation_count

    # No per-recommendation primary-key SELECT against circles.
    per_id_gets = [
        sql
        for sql in normalized
        if "from circles" in sql and re.search(r"\bcircles\.id\s*=\s*", sql)
    ]
    assert per_id_gets == []


# ---------------------------------------------------------------------------
# Planted scenarios
# ---------------------------------------------------------------------------


def test_planted_user_7_obvious_matches(api_client: TestClient) -> None:
    response = api_client.get(_recommendations_url(7, limit=5))
    assert response.status_code == 200
    body = response.json()
    ids = {card["circle_id"] for card in body["recommendations"]}
    assert {5, 6}.issubset(ids)

    by_id = {card["circle_id"]: card for card in body["recommendations"]}
    reason_5 = by_id[5]["reason"].lower()
    reason_6 = by_id[6]["reason"].lower()
    assert "leadership skills" in reason_5 or "leadership" in reason_5
    assert "interest" in reason_5
    assert "public speaking" in reason_6
    assert "interest" in reason_6
    for circle_id in (5, 6):
        reason = by_id[circle_id]["reason"].lower()
        if "recent" in reason:
            assert "snapshot" in reason


def test_planted_user_15_near_duplicate_cap(api_client: TestClient) -> None:
    response = api_client.get(_recommendations_url(15, limit=5))
    assert response.status_code == 200
    body = response.json()
    ids = [card["circle_id"] for card in body["recommendations"]]
    negotiation_dupes = [cid for cid in ids if cid in {10, 11, 12}]
    assert len(negotiation_dupes) <= 2

    assert "confidence" in [card["topic"] for card in body["recommendations"]] or any(
        "confidence" in card["reason"].lower() or card["topic"] == "confidence"
        for card in body["recommendations"]
    )

    for card in body["recommendations"]:
        reason = card["reason"].lower()
        if card["topic"] != "negotiation" and "negotiation" in reason:
            # Tag-only style should not over-claim primary focus.
            assert "matches your interest in negotiation" not in reason
        if "recent" in reason:
            assert "snapshot" in reason


def test_planted_user_23_full_inactive_traps(api_client: TestClient) -> None:
    response = api_client.get(_recommendations_url(23, limit=5))
    assert response.status_code == 200
    body = response.json()
    ids = [card["circle_id"] for card in body["recommendations"]]
    assert ids[0] == 22
    assert 20 not in ids
    assert 21 not in ids

    top = body["recommendations"][0]
    assert top["join_policy"] == "request"
    reason = top["reason"].lower()
    assert "getting promoted" in reason
    assert "join immediately" not in reason
    assert "open to new members" not in reason
    assert "recent member activity" in reason
    assert "available snapshot" in reason
    assert "has recent member activity" not in reason
    assert "right now" not in reason


def test_planted_user_42_cold_start(api_client: TestClient) -> None:
    response = api_client.get(_recommendations_url(42, limit=5))
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"]

    for card in body["recommendations"]:
        reason = card["reason"].lower()
        assert "your interest" not in reason
        assert "you're interested" not in reason
        assert "industry" not in reason
        assert "job title" not in reason
        assert "nearby" not in reason
        if "recent" in reason:
            assert "snapshot" in reason

    top = body["recommendations"][0]
    if top["topic"] is None:
        assert "focuses on" not in top["reason"].lower()
        assert top["reason"].strip()


# ---------------------------------------------------------------------------
# Dataset-wide API validation
# ---------------------------------------------------------------------------


def test_all_users_api_validation(api_app: FastAPI, api_client: TestClient) -> None:
    limits = (1, 5, 10, 20)
    with Session(api_app.state.engine) as session:
        user_ids = list(session.scalars(select(User.id).order_by(User.id)).all())
        assert len(user_ids) == 100
        circles = {
            c.id: c
            for c in session.scalars(
                select(Circle).options(selectinload(Circle.primary_topic))
            ).all()
        }
        memberships = {
            uid: set(
                session.scalars(
                    select(Membership.circle_id).where(Membership.user_id == uid)
                ).all()
            )
            for uid in user_ids
        }

    for user_id in user_ids:
        for limit in limits:
            response = api_client.get(_recommendations_url(user_id, limit=limit))
            assert response.status_code == 200, (
                f"user={user_id} limit={limit} -> {response.status_code}"
            )
            body = response.json()
            parsed = CircleRecommendationsResponse.model_validate(body)
            _assert_no_internal_fields(body)
            assert parsed.user_id == user_id
            assert len(parsed.recommendations) <= limit

            seen: set[int] = set()
            for index, card in enumerate(parsed.recommendations, start=1):
                assert card.rank == index
                assert card.circle_id not in seen
                seen.add(card.circle_id)
                assert card.circle_id not in memberships[user_id]
                assert card.reason.strip()
                assert card.slug
                assert card.name
                assert card.format in {"in_person", "virtual", "hybrid"}
                assert card.join_policy in {"open", "request"}
                if "recent" in card.reason.lower():
                    assert "snapshot" in card.reason.lower()

                circle = circles[card.circle_id]
                assert circle.access == "public"
                assert not (
                    circle.max_members is not None
                    and circle.member_count >= circle.max_members
                )
                assert not is_dormant(
                    feed_posts_30d=circle.feed_posts_30d,
                    chat_messages_30d=circle.chat_messages_30d,
                    last_activity_at=circle.last_activity_at,
                )
                topic_slug = (
                    circle.primary_topic.slug if circle.primary_topic is not None else None
                )
                assert card.topic == topic_slug
                assert card.description == circle.description
                assert card.cover_image_url == circle.cover_image_url
                assert card.slug == circle.slug
                assert card.name == circle.name
                assert card.format == circle.format
                assert card.join_policy == circle.join_policy

            again = api_client.get(_recommendations_url(user_id, limit=limit))
            assert again.status_code == 200
            assert again.json() == body

            with Session(api_app.state.engine) as session:
                service_ids = [
                    rec.circle_id
                    for rec in recommend_circles(session, user_id, limit=limit)
                ]
            assert [c.circle_id for c in parsed.recommendations] == service_ids
