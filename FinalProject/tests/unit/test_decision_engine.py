import pytest

from credit_risk.serving.decision_engine import credit_score, credit_tier, decide, recommended_limit, risk_decision


@pytest.mark.parametrize(
    ("probability", "expected"),
    [(0.0, "APPROVE"), (0.29, "APPROVE"), (0.30, "REVIEW"), (0.59, "REVIEW"), (0.60, "DECLINE"), (1.0, "DECLINE")],
)
def test_risk_decision_thresholds(probability, expected):
    assert risk_decision(probability, 0.30, 0.60) == expected


@pytest.mark.parametrize(("probability", "expected"), [(0.0, 850), (1.0, 300), (0.5, 575), (0.4, 630)])
def test_credit_score_scale(probability, expected):
    assert credit_score(probability) == expected


def test_credit_score_is_clamped():
    assert credit_score(-1.0) == 850
    assert credit_score(2.0) == 300


@pytest.mark.parametrize(
    ("score", "tier"), [(850, "PRIME"), (740, "PRIME"), (739, "NEAR_PRIME"), (670, "NEAR_PRIME"), (580, "SUBPRIME")]
)
def test_credit_tier_boundaries(score, tier):
    assert credit_tier(score) == tier


def test_credit_tier_high_risk():
    assert credit_tier(579) == "HIGH_RISK"


def test_recommended_limit_rules():
    assert recommended_limit("APPROVE", 100_000) == 125_000
    assert recommended_limit("APPROVE", 1_000_000) == 500_000
    assert recommended_limit("REVIEW", 100_000) == 50_000
    assert recommended_limit("REVIEW", 1_000_000) == 100_000
    assert recommended_limit("DECLINE", 100_000) == 0.0


def test_decide_combines_rules():
    outcome = decide(0.1, 200_000, 0.3, 0.6)
    assert outcome.decision == "APPROVE"
    assert outcome.credit_score == 795
    assert outcome.credit_tier == "PRIME"
    assert outcome.recommended_limit == 250_000
