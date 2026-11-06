"""Unit tests for ADR 005 diversity reranking."""

from __future__ import annotations

from collections import Counter

from app.recommendations.constants import (
    PERSONALIZATION_EXPLICIT,
    SAME_TOPIC_PENALTY,
)
from app.recommendations.diversity import adjusted_score, diversify, same_topic_penalty
from app.recommendations.types import ScoredCandidate, ScoreEvidence


def _evidence(**overrides) -> ScoreEvidence:
    base = dict(
        personalization_mode=PERSONALIZATION_EXPLICIT,
        relevance_score=1.0,
        relevance_source="primary_topic",
        matched_topic_or_tag="negotiation",
        relevance_is_inferred=False,
        feed_quality=0.5,
        chat_quality=0.5,
        recency_quality=0.5,
        quality_score=0.5,
        relevance_weight=0.7,
        quality_weight=0.3,
        base_score=0.85,
    )
    base.update(overrides)
    return ScoreEvidence(**base)


def _cand(
    circle_id: int,
    base_score: float,
    topic: str | None,
    name: str | None = None,
) -> ScoredCandidate:
    return ScoredCandidate(
        circle_id=circle_id,
        circle_name=name or f"Circle {circle_id}",
        primary_topic_slug=topic,
        base_score=base_score,
        evidence=_evidence(
            base_score=base_score,
            matched_topic_or_tag=topic,
        ),
    )


def test_one_repeat_applies_010_penalty() -> None:
    counts = Counter({"negotiation": 1})
    assert same_topic_penalty("negotiation", counts) == SAME_TOPIC_PENALTY
    candidate = _cand(1, 0.90, "negotiation")
    assert adjusted_score(candidate, counts) == 0.90 - 0.10


def test_two_repeats_apply_020_penalty() -> None:
    counts = Counter({"negotiation": 2})
    candidate = _cand(1, 0.90, "negotiation")
    assert adjusted_score(candidate, counts) == 0.90 - 0.20


def test_null_topics_are_not_grouped() -> None:
    candidates = [
        _cand(1, 0.90, None),
        _cand(2, 0.89, None),
        _cand(3, 0.88, None),
        _cand(4, 0.50, "allyship"),
    ]
    result = diversify(candidates, limit=3)
    assert [r.circle_id for r in result] == [1, 2, 3]
    # Adjusted scores equal base scores — no null-topic penalty.
    assert all(abs(r.adjusted_score - r.base_score) < 1e-12 for r in result)


def test_conditional_top_five_cap_defers_third_same_topic() -> None:
    # Three strong negotiation Circles plus a slightly weaker alternative.
    candidates = [
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
        _cand(12, 0.93, "negotiation"),
        _cand(20, 0.80, "confidence"),
        _cand(21, 0.70, "allyship"),
    ]
    result = diversify(candidates, limit=5)
    first_five_ids = [r.circle_id for r in result]
    # With 0.93 - 0.80 = 0.13 <= 0.25, the third negotiation is deferred.
    assert first_five_ids[:3] == [10, 11, 20]
    assert 12 in first_five_ids  # deferred, not discarded
    negotiation_in_top5 = sum(
        1 for r in result if r.primary_topic_slug == "negotiation"
    )
    assert negotiation_in_top5 <= 3


def test_greater_than_025_exception_allows_third() -> None:
    candidates = [
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
        _cand(12, 0.93, "negotiation"),
        _cand(20, 0.60, "confidence"),  # 0.93 - 0.60 = 0.33 > 0.25
    ]
    result = diversify(candidates, limit=4)
    assert [r.circle_id for r in result] == [10, 11, 12, 20]


def test_exactly_025_does_not_trigger_exception() -> None:
    candidates = [
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
        _cand(12, 0.90, "negotiation"),
        _cand(20, 0.65, "confidence"),  # 0.90 - 0.65 = 0.25 exactly
    ]
    result = diversify(candidates, limit=4)
    assert result[2].circle_id == 20
    assert result[3].circle_id == 12


def test_cap_relaxed_after_first_five() -> None:
    # Alternatives stay within the 0.25 exception margin so the top-five cap
    # defers extra negotiation picks; after position 5 the cap no longer applies.
    candidates = [
        _cand(1, 1.00, "negotiation"),
        _cand(2, 0.99, "negotiation"),
        _cand(3, 0.90, "confidence"),
        _cand(4, 0.89, "allyship"),
        _cand(5, 0.88, "leadership-skills"),
        _cand(6, 0.97, "negotiation"),  # 0.97 - 0.90 = 0.07 <= 0.25 → deferred in top 5
        _cand(7, 0.96, "negotiation"),
        _cand(8, 0.95, "negotiation"),
    ]
    result = diversify(candidates, limit=8)
    assert len(result) == 8
    assert {r.circle_id for r in result} == {1, 2, 3, 4, 5, 6, 7, 8}
    top5_ids = [r.circle_id for r in result[:5]]
    top5_negotiation = [
        r for r in result[:5] if r.primary_topic_slug == "negotiation"
    ]
    assert len(top5_negotiation) == 2
    assert set(top5_ids) == {1, 2, 3, 4, 5}
    # Positions 6–8 absorb the deferred negotiation Circles.
    assert [r.circle_id for r in result[5:]] == [6, 7, 8]


def test_no_duplicate_circle_ids() -> None:
    candidates = [_cand(i, 0.5 + i * 0.01, "negotiation") for i in range(1, 8)]
    result = diversify(candidates, limit=5)
    ids = [r.circle_id for r in result]
    assert len(ids) == len(set(ids))


def test_input_order_does_not_affect_output() -> None:
    candidates = [
        _cand(3, 0.80, "allyship"),
        _cand(1, 0.95, "negotiation"),
        _cand(2, 0.90, "confidence"),
    ]
    forward = diversify(candidates, limit=3)
    reverse = diversify(list(reversed(candidates)), limit=3)
    assert [r.circle_id for r in forward] == [r.circle_id for r in reverse]
    assert [r.circle_id for r in forward] == [1, 2, 3]


def test_deferred_candidates_remain_available() -> None:
    candidates = [
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
        _cand(12, 0.93, "negotiation"),
        _cand(20, 0.80, "confidence"),
    ]
    result = diversify(candidates, limit=4)
    assert sorted(r.circle_id for r in result) == [10, 11, 12, 20]
    assert len(result) == 4


def test_empty_and_short_candidate_lists() -> None:
    assert diversify([], limit=5) == []
    single = diversify([_cand(1, 0.5, "allyship")], limit=5)
    assert len(single) == 1
    assert diversify([_cand(1, 0.5, "allyship")], limit=0) == []


def test_tie_break_lowest_circle_id() -> None:
    candidates = [
        _cand(5, 0.80, "allyship"),
        _cand(2, 0.80, "confidence"),
        _cand(9, 0.80, "leadership-skills"),
    ]
    result = diversify(candidates, limit=3)
    assert [r.circle_id for r in result] == [2, 5, 9]


def test_does_not_mutate_input_candidates() -> None:
    candidates = [
        _cand(1, 0.9, "negotiation"),
        _cand(2, 0.8, "confidence"),
    ]
    original_scores = [c.base_score for c in candidates]
    diversify(candidates, limit=2)
    assert [c.base_score for c in candidates] == original_scores
