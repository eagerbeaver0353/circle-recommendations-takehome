"""Unit tests for ADR 005 diversity reranking (including relevance-aware cap)."""

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
    *,
    name: str | None = None,
    relevance_score: float = 1.0,
    relevance_source: str | None = "primary_topic",
) -> ScoredCandidate:
    source = relevance_source
    if relevance_score <= 0:
        source = None
    elif relevance_score < 1.0 and relevance_source == "primary_topic":
        source = "tag"
    return ScoredCandidate(
        circle_id=circle_id,
        circle_name=name or f"Circle {circle_id}",
        primary_topic_slug=topic,
        base_score=base_score,
        evidence=_evidence(
            base_score=base_score,
            relevance_score=relevance_score,
            relevance_source=source,
            matched_topic_or_tag=topic if relevance_score > 0 else None,
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
        _cand(1, 0.90, None, relevance_score=0.0),
        _cand(2, 0.89, None, relevance_score=0.0),
        _cand(3, 0.88, None, relevance_score=0.0),
        _cand(4, 0.50, "allyship"),
    ]
    result = diversify(candidates, limit=3)
    assert [r.circle_id for r in result] == [1, 2, 3]
    assert all(abs(r.adjusted_score - r.base_score) < 1e-12 for r in result)


def test_conditional_top_five_cap_defers_third_same_topic() -> None:
    # Three strong negotiation Circles plus a slightly weaker alternative.
    # Gap 0.13 <= 0.25, so third is deferred even without relevance priority.
    candidates = [
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
        _cand(12, 0.93, "negotiation"),
        _cand(20, 0.80, "confidence"),
        _cand(21, 0.70, "allyship"),
    ]
    result = diversify(candidates, limit=5)
    first_five_ids = [r.circle_id for r in result]
    assert first_five_ids[:3] == [10, 11, 20]
    assert 12 in first_five_ids  # deferred, not discarded
    negotiation_in_top5 = sum(
        1 for r in result if r.primary_topic_slug == "negotiation"
    )
    assert negotiation_in_top5 <= 3


def test_positive_relevance_blocks_gap_exception() -> None:
    """A relevant different-topic alternative blocks the >0.25 gap bypass."""
    candidates = [
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
        _cand(12, 0.93, "negotiation"),
        # Gap 0.33 > 0.25, but positive relevance must still win.
        _cand(20, 0.60, "confidence", relevance_score=1.0),
    ]
    result = diversify(candidates, limit=4)
    assert [r.circle_id for r in result] == [10, 11, 20, 12]


def test_tag_match_relevance_counts_as_positive() -> None:
    """Secondary-tag relevance (0.25) is enough to block the gap exception."""
    candidates = [
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
        _cand(12, 0.93, "negotiation"),
        _cand(
            38,
            0.40,
            "public-speaking",
            relevance_score=0.25,
            relevance_source="tag",
        ),
    ]
    result = diversify(candidates, limit=4)
    assert [r.circle_id for r in result] == [10, 11, 38, 12]


def test_zero_relevance_does_not_block_gap_exception() -> None:
    """Unrelated Circles (relevance 0) do not trigger the new priority."""
    candidates = [
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
        _cand(12, 0.93, "negotiation"),
        _cand(20, 0.60, "confidence", relevance_score=0.0),  # 0.93-0.60=0.33 > 0.25
    ]
    result = diversify(candidates, limit=4)
    assert [r.circle_id for r in result] == [10, 11, 12, 20]


def test_exactly_025_does_not_trigger_exception() -> None:
    candidates = [
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
        _cand(12, 0.90, "negotiation"),
        # Exact 0.25 gap + zero relevance → defer third negotiation.
        _cand(20, 0.65, "confidence", relevance_score=0.0),
    ]
    result = diversify(candidates, limit=4)
    assert result[2].circle_id == 20
    assert result[3].circle_id == 12


def test_exhausted_topic_cap_is_not_a_viable_alternative() -> None:
    """A different-topic Circle that would itself exceed the cap is not viable."""
    candidates = [
        _cand(1, 1.00, "negotiation"),
        _cand(2, 0.99, "negotiation"),
        _cand(3, 0.98, "confidence"),
        _cand(4, 0.97, "confidence"),
        # Third negotiation: only remaining "alternative" is a third confidence,
        # which also exceeds the cap, so the gap exception may apply.
        _cand(5, 0.96, "negotiation"),
        _cand(6, 0.50, "confidence", relevance_score=1.0),
    ]
    result = diversify(candidates, limit=5)
    ids = [r.circle_id for r in result]
    # Greedy interleaves topics via the same-topic penalty:
    # 1 (neg), 3 (conf), 2 (neg), 4 (conf).
    assert ids[:4] == [1, 3, 2, 4]
    # Circle 6 would be a third confidence → not a viable positively relevant alt.
    # Circle 5 may then use the gap exception (0.96 - 0.50 = 0.46 > 0.25).
    assert ids[4] == 5
    assert 6 not in ids[:5]


def test_gap_exception_when_no_positive_relevance_alternative() -> None:
    candidates = [
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
        _cand(12, 0.93, "negotiation"),
        _cand(20, 0.60, "confidence", relevance_score=0.0),
    ]
    result = diversify(candidates, limit=4)
    assert [r.circle_id for r in result] == [10, 11, 12, 20]


def test_cap_relaxed_after_first_five() -> None:
    candidates = [
        _cand(1, 1.00, "negotiation"),
        _cand(2, 0.99, "negotiation"),
        _cand(3, 0.90, "confidence", relevance_score=0.0),
        _cand(4, 0.89, "allyship", relevance_score=0.0),
        _cand(5, 0.88, "leadership-skills", relevance_score=0.0),
        _cand(6, 0.97, "negotiation"),
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


def test_relevance_priority_with_input_order_independence() -> None:
    candidates = [
        _cand(12, 0.93, "negotiation"),
        _cand(20, 0.60, "confidence", relevance_score=1.0),
        _cand(10, 0.95, "negotiation"),
        _cand(11, 0.94, "negotiation"),
    ]
    forward = [r.circle_id for r in diversify(candidates, limit=4)]
    reverse = [r.circle_id for r in diversify(list(reversed(candidates)), limit=4)]
    assert forward == reverse == [10, 11, 20, 12]
