"""Development-only recommendation diagnostics.

Prints top-five rankings for planted assessment users. Not a production API.

Usage::

    python -m app.recommendations.diagnostics
"""

from __future__ import annotations

import sys

from sqlalchemy.orm import Session

from app.database import create_db_engine
from app.recommendations.service import recommend_circles

# Planted assessment user IDs — diagnostics / tests only.
DIAGNOSTIC_USER_IDS = (7, 15, 23, 42)


def format_recommendation_row(rec) -> str:
    evidence = rec.evidence
    topic = rec.primary_topic_slug or "(none)"
    return (
        f"  #{rec.rank}  circle={rec.circle_id} {rec.circle_name!r}\n"
        f"      topic={topic}  mode={evidence.personalization_mode}\n"
        f"      relevance={evidence.relevance_score:.4f}  "
        f"quality={evidence.quality_score:.4f}  "
        f"base={rec.base_score:.4f}  adjusted={rec.adjusted_score:.4f}"
    )


def print_diagnostics(
    session: Session,
    user_ids: tuple[int, ...] = DIAGNOSTIC_USER_IDS,
    *,
    limit: int = 5,
    file=sys.stdout,
) -> None:
    """Print top-*limit* recommendations for each diagnostic user."""
    for user_id in user_ids:
        print(f"\n=== User {user_id} — top {limit} ===", file=file)
        recommendations = recommend_circles(session, user_id, limit=limit)
        if not recommendations:
            print("  (no recommendations)", file=file)
            continue
        for rec in recommendations:
            print(format_recommendation_row(rec), file=file)


def main(argv: list[str] | None = None) -> int:
    del argv
    engine = create_db_engine()
    with Session(engine) as session:
        print_diagnostics(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
