"""Circle recommendation engine (Phase 2).

Public entry point: ``recommend_circles``. Internal scoring evidence is intended
for Phase 3 explanation generation and is not an HTTP response contract.
"""

from app.recommendations.service import UserNotFoundError, recommend_circles
from app.recommendations.types import Recommendation, ScoredCandidate, ScoreEvidence

__all__ = [
    "Recommendation",
    "ScoreEvidence",
    "ScoredCandidate",
    "UserNotFoundError",
    "recommend_circles",
]
