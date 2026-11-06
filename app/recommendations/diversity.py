"""Deterministic greedy diversification reranking (ADR 005).

Pure functions — does not mutate input candidate records.

Amendment: within the first five positions, a positively relevant
(``relevance_score > 0``) different-topic alternative that itself fits the
topic cap takes priority over the base-score gap exception.
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


def _has_positively_relevant_cap_safe_alternative(
    candidate: ScoredCandidate,
    remaining: Sequence[ScoredCandidate],
    selected_topic_counts: Counter[str],
    selected_count: int,
) -> bool:
    """True when a different-topic remaining Circle has relevance > 0 and fits the cap.

    Uses structured scoring evidence only — no second relevance calculation.
    A candidate that has itself exhausted its topic cap is not a viable alternative.
    """
    topic = candidate.primary_topic_slug
    for other in remaining:
        if other.circle_id == candidate.circle_id:
            continue
        if other.primary_topic_slug == topic:
            continue
        if other.evidence.relevance_score <= 0:
            continue
        if _would_exceed_topic_cap(other, selected_topic_counts, selected_count):
            continue
        return True
    return False


def _pick_next(
    remaining: list[ScoredCandidate],
    selected: list[ScoredCandidate],
    selected_topic_counts: Counter[str],
) -> ScoredCandidate:
    """Choose the next Circle under adjusted-score ranking and the topic cap.

    Within the first five positions, if selecting a candidate would exceed the
    per-topic cap, positively relevant different-topic alternatives that still
    fit the cap take priority over the base-score gap exception.
    """
    ranked = sorted(
        remaining,
        key=lambda c: _selection_sort_key(c, selected_topic_counts),
    )
    selected_count = len(selected)

    for candidate in ranked:
        if not _would_exceed_topic_cap(
            candidate, selected_topic_counts, selected_count
        ):
            return candidate

        # Would be a third+ same-topic pick inside the top five.
        if _has_positively_relevant_cap_safe_alternative(
            candidate,
            remaining,
            selected_topic_counts,
            selected_count,
        ):
            # Defer — do not let the gap exception bypass a relevant alternative.
            continue

        # No suitable positively relevant alternative: original gap exception.
        alternative = _best_alternative_by_base(candidate, remaining)
        if alternative is None:
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
    - Positively relevant alternatives outrank the 0.25 gap exception
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
