"""Centralized ranking constants for the Circle recommendation engine.

All numerical thresholds and weights used by eligibility, scoring, and
diversification live here so they are easy to audit and tune together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

# Fixed dataset snapshot reference (UTC). Do not use wall-clock time.
SNAPSHOT_REFERENCE: Final[datetime] = datetime(2026, 9, 21, 0, 0, 0, tzinfo=UTC)

# --- Eligibility (ADR 003) -------------------------------------------------

DORMANCY_MAX_CHAT_MESSAGES_30D: Final[int] = 3
DORMANCY_INACTIVITY_DAYS: Final[int] = 60
PUBLIC_ACCESS: Final[str] = "public"

# --- Topic relevance (ADR 004) ---------------------------------------------

PRIMARY_TOPIC_RELEVANCE: Final[float] = 1.0
TAG_MATCH_RELEVANCE: Final[float] = 0.25
MIN_MEMBERSHIPS_FOR_INFERENCE: Final[int] = 2

# --- Activity quality (ADR 004) --------------------------------------------

FEED_ACTIVITY_WEIGHT: Final[float] = 0.55
CHAT_ACTIVITY_WEIGHT: Final[float] = 0.30
RECENCY_ACTIVITY_WEIGHT: Final[float] = 0.15

# Fixed reference counts for log1p diminishing-returns normalization.
FEED_REFERENCE_COUNT: Final[int] = 20
CHAT_REFERENCE_COUNT: Final[int] = 200

# Recency half-life relative to SNAPSHOT_REFERENCE.
RECENCY_HALF_LIFE_DAYS: Final[float] = 14.0

# --- Confidence-aware score blend (ADR 004) --------------------------------

# personalization_mode -> (relevance_weight, quality_weight); weights sum to 1.
SCORE_WEIGHTS: Final[dict[str, tuple[float, float]]] = {
    "explicit": (0.70, 0.30),
    "inferred": (0.25, 0.75),
    "cold_start": (0.00, 1.00),
}

PERSONALIZATION_EXPLICIT: Final[str] = "explicit"
PERSONALIZATION_INFERRED: Final[str] = "inferred"
PERSONALIZATION_COLD_START: Final[str] = "cold_start"

# --- Diversity reranking (ADR 005) -----------------------------------------

SAME_TOPIC_PENALTY: Final[float] = 0.10
TOP_FIVE_TOPIC_CAP: Final[int] = 2
TOP_FIVE_CAP_POSITIONS: Final[int] = 5
TOPIC_CAP_EXCEPTION_MARGIN: Final[float] = 0.25
