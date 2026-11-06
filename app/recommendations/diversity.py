"""Deterministic greedy diversification reranking (ADR 005).

Pure functions — does not mutate input candidate records.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from app.recommendations.constants import (
    SAME_TOPIC_PENALTY,
    TOP_FIVE_CAP_POSITIONS,
    TOP_FIVE_TOPIC_CAP,
    TOPIC_CAP_EXCEPTION_MARGIN,
)
from app.recommendations.types import Recommendation, ScoredCandidate


def same_topic_penalty(
    primary_topic_slug: str | None,
    selected_topic_counts: Counter[str],
    *,
    penalty_per_repeat: float = SAME_TOPIC_PENALTY,
) -> float:
    """Return the diversity penalty for a candidate given already-selected topics.

    Null primary topics receive no same-topic penalty and are never grouped
    with other null-topic Circles.
    """
    if primary_topic_slug is None:
        return 0.0
    return penalty_per_repeat * selected_topic_counts[primary_topic_slug]


def adjusted_score(
    candidate: ScoredCandidate,
    selected_topic_counts: Counter[str],
    *,
    penalty_per_repeat: float = SAME_TOPIC_PENALTY,
) -> float:
    """``base_score - penalty`` without mutating the candidate's base score."""
    return candidate.base_score - same_topic_penalty(
        candidate.primary_topic_slug,
        selected_topic_counts,
        penalty_per_repeat=penalty_per_repeat,
    )


def _selection_sort_key(
    candidate: ScoredCandidate,
    selected_topic_counts: Counter[str],
) -> tuple[float, float, int]:
    """Tie-breakers: highest adjusted, highest base, lowest Circle ID."""
    adj = adjusted_score(candidate, selected_topic_counts)
    # Negate scores for ascending sort; keep ID ascending as the final key.
    return (-adj, -candidate.base_score, candidate.circle_id)


def _would_exceed_topic_cap(
    candidate: ScoredCandidate,
    selected_topic_counts: Counter[str],
    selected_count: int,
) -> bool:
    """True when selecting *candidate* would be a third+ same-topic in top five."""
    if selected_count >= TOP_FIVE_CAP_POSITIONS:
        return False
    topic = candidate.primary_topic_slug
    if topic is None:
        return False
    return selected_topic_counts[topic] >= TOP_FIVE_TOPIC_CAP


def _best_alternative_by_base(
    candidate: ScoredCandidate,
    remaining: Sequence[ScoredCandidate],
) -> ScoredCandidate | None:
    """Highest-base-score remaining candidate from another (or null) topic."""
    topic = candidate.primary_topic_slug
    alternatives = [
        other
        for other in remaining
        if other.circle_id != candidate.circle_id
        and other.primary_topic_slug != topic
    ]
    if not alternatives:
        return None
    # Highest base score, then lowest Circle ID for stability.
    return min(alternatives, key=lambda c: (-c.base_score, c.circle_id))


def _allows_topic_cap_exception(
    candidate: ScoredCandidate,
    alternative: ScoredCandidate,
    *,
    margin: float = TOPIC_CAP_EXCEPTION_MARGIN,
) -> bool:
    """Allow a third same-topic pick when base exceeds the alternative by > margin.

    Exactly ``margin`` difference does **not** trigger the exception.
    """
    return candidate.base_score > alternative.base_score + margin


def _pick_next(
    remaining: list[ScoredCandidate],
    selected: list[ScoredCandidate],
    selected_topic_counts: Counter[str],
) -> ScoredCandidate:
    """Choose the next Circle under adjusted-score ranking and the topic cap."""
    ranked = sorted(
        remaining,
        key=lambda c: _selection_sort_key(c, selected_topic_counts),
    )

    for candidate in ranked:
        if not _would_exceed_topic_cap(
            candidate, selected_topic_counts, len(selected)
        ):
            return candidate

        alternative = _best_alternative_by_base(candidate, remaining)
        if alternative is None:
            # No suitable alternative remains — allow the third.
            return candidate
        if _allows_topic_cap_exception(candidate, alternative):
            return candidate
        # Defer this third-same-topic candidate; try the next ranked option.
        continue

    # All remaining candidates were deferred somehow; fall back to greedy best.
    return ranked[0]


def diversify(
    candidates: Sequence[ScoredCandidate],
    limit: int,
) -> list[Recommendation]:
    """Greedy diversity reranking before applying the final result limit.

    Properties:
    - Never selects a Circle twice
    - Never reintroduces candidates outside the input set
    - Returns at most *limit* results
    - Handles empty or short candidate lists
    - Independent of input collection order
    - Does not mutate input records
    - Conditional topic cap applies only to the first five positions
    """
    if limit <= 0 or not candidates:
        return []

    # Deterministic working set independent of input order.
    remaining = sorted(
        candidates,
        key=lambda c: (-c.base_score, c.circle_id),
    )
    selected: list[ScoredCandidate] = []
    adjusted_at_selection: list[float] = []
    topic_counts: Counter[str] = Counter()

    while remaining and len(selected) < limit:
        chosen = _pick_next(remaining, selected, topic_counts)
        adj = adjusted_score(chosen, topic_counts)
        selected.append(chosen)
        adjusted_at_selection.append(adj)
        remaining = [c for c in remaining if c.circle_id != chosen.circle_id]
        if chosen.primary_topic_slug is not None:
            topic_counts[chosen.primary_topic_slug] += 1

    return [
        Recommendation(
            rank=index,
            circle_id=candidate.circle_id,
            circle_name=candidate.circle_name,
            primary_topic_slug=candidate.primary_topic_slug,
            base_score=candidate.base_score,
            adjusted_score=adjusted_at_selection[index - 1],
            evidence=candidate.evidence,
        )
        for index, candidate in enumerate(selected, start=1)
    ]
