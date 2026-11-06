"""Public Pydantic response schemas for the Circle recommendations API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RecommendationCard(BaseModel):
    """Member-facing recommendation card. Excludes internal scoring fields."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(..., ge=1, description="1-based position in the ranked list")
    circle_id: int
    slug: str
    name: str
    description: str | None
    topic: str | None = Field(
        ...,
        description="Primary topic slug, or null when the Circle has no primary topic",
    )
    format: Literal["in_person", "virtual", "hybrid"]
    join_policy: Literal["open", "request"]
    cover_image_url: str | None
    reason: str = Field(..., min_length=1, description="Evidence-based explanation")


class CircleRecommendationsResponse(BaseModel):
    """Top-level response for personalized Circle recommendations."""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    recommendations: list[RecommendationCard]


class HealthResponse(BaseModel):
    """Minimal readiness payload for operators and load balancers."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    database: Literal["ready"]
