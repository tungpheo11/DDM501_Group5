import pytest

from credit_risk.evaluation.model_validation import GateDecision, PromotionPolicy, compare_champion_challenger


def _m(auc: float, loss: float) -> dict[str, float]:
    return {"roc_auc": auc, "expected_loss": loss, "f1_score": 0.5}


def test_first_model_is_promoted_when_above_floor():
    decision = compare_champion_challenger(_m(0.75, 1.1), None)
    assert decision.promote
    assert decision.champion is None
    assert "no current champion" in decision.reasons[0]


def test_model_below_floor_is_never_promoted():
    assert not compare_champion_challenger(_m(0.65, 0.5), None).promote
    decision = compare_champion_challenger(_m(0.69, 0.5), _m(0.60, 2.0))
    assert not decision.promote
    assert "below floor" in decision.reasons[0]


def test_better_auc_and_lower_loss_promotes():
    decision = compare_champion_challenger(_m(0.78, 1.0), _m(0.75, 1.2))
    assert decision.promote
    assert decision.roc_auc_delta == pytest.approx(0.03)
    assert decision.expected_loss_delta == pytest.approx(-0.2)


def test_small_auc_drop_with_lower_loss_promotes():
    assert compare_champion_challenger(_m(0.747, 1.0), _m(0.750, 1.2)).promote


def test_auc_drop_beyond_margin_rejects():
    decision = compare_champion_challenger(_m(0.74, 0.8), _m(0.75, 1.2))
    assert not decision.promote
    assert "ROC-AUC drop" in decision.reasons[-1]


def test_higher_loss_rejects_even_with_better_auc():
    decision = compare_champion_challenger(_m(0.80, 1.3), _m(0.75, 1.2))
    assert not decision.promote
    assert "financial loss" in decision.reasons[-1]


def test_identical_model_is_not_promoted():
    decision = compare_champion_challenger(_m(0.75, 1.2), _m(0.75, 1.2))
    assert not decision.promote
    assert "no strict improvement" in decision.reasons[-1]


def test_min_loss_improvement_requires_meaningful_saving():
    policy = PromotionPolicy(min_loss_improvement=0.05)
    assert not compare_champion_challenger(_m(0.75, 1.19), _m(0.75, 1.2), policy).promote
    assert compare_champion_challenger(_m(0.75, 1.10), _m(0.75, 1.2), policy).promote
    assert compare_champion_challenger(_m(0.76, 1.19), _m(0.75, 1.2), policy).promote


def test_decision_is_serialisable():
    payload = compare_champion_challenger(_m(0.78, 1.0), _m(0.75, 1.2)).to_dict()
    assert payload["promote"] is True
    assert payload["challenger"] == {"roc_auc": 0.78, "expected_loss": 1.0}
    assert isinstance(GateDecision(promote=False).reasons, list)
