"""FastAPI application for personalized Circle recommendations (Phase 3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.deps import check_database_ready, configure_engine, get_db
from app.recommendations.cards import build_recommendation_response
from app.recommendations.service import UserNotFoundError, recommend_circles
from app.schemas import CircleRecommendationsResponse, HealthResponse


def create_app(*, database_url: str | None = None) -> FastAPI:
    """Build a FastAPI app, optionally bound to a specific database URL.

    Does not seed the database. Seeding remains ``python -m app.seed``.
    """
    # Bind the process-level engine once at construction time. Tests pass an
    # isolated temporary SQLite URL; production uses CIRCLES_DATABASE_URL.
    configure_engine(database_url)

    application = FastAPI(
        title="Lean In Circle Recommendations",
        description=(
            "Personalized Circle recommendations with short, evidence-based "
            "member-facing explanations."
        ),
        version="0.3.0",
    )
    _register_routes(application)
    return application


def _register_routes(application: FastAPI) -> None:
    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["health"],
        summary="Application and database readiness",
    )
    def health(session: Annotated[Session, Depends(get_db)]) -> HealthResponse:
        if not check_database_ready(session):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database is not ready",
            )
        return HealthResponse(status="ok", database="ready")

    @application.get(
        "/api/v1/users/{user_id}/circle-recommendations",
        response_model=CircleRecommendationsResponse,
        tags=["recommendations"],
        summary="Personalized Circle recommendations for a member",
        responses={
            404: {
                "description": "User not found",
                "content": {
                    "application/json": {"example": {"detail": "User not found"}}
                },
            },
            422: {"description": "Invalid path or query parameters"},
        },
    )
    def get_circle_recommendations(
        user_id: Annotated[
            int,
            Path(
                gt=0,
                description="Positive member user ID",
                examples=[7, 15, 23, 42],
            ),
        ],
        session: Annotated[Session, Depends(get_db)],
        limit: Annotated[
            int,
            Query(
                ge=1,
                le=20,
                description="Maximum number of recommendations to return (1–20)",
            ),
        ] = 5,
    ) -> CircleRecommendationsResponse:
        """Return ranked Circles the member may explore, with short reasons.

        Ranking comes from the Phase 2 recommendation service. This endpoint
        only hydrates card metadata and explanations — it never alters scores.
        """
        try:
            recommendations = recommend_circles(session, user_id, limit=limit)
        except UserNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            ) from exc

        return build_recommendation_response(session, user_id, recommendations)


# Default ASGI app for ``uvicorn app.main:app``.
app = create_app()
