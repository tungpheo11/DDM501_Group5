import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from credit_risk.data.schema import ALL_FEATURES
from credit_risk.responsible_ai import fairness


def _cardholders(n: int = 400, seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({column: rng.integers(0, 3, n) for column in ALL_FEATURES}).astype(float)
    frame["SEX"] = rng.integers(1, 3, n)
    frame["EDUCATION"] = rng.integers(1, 5, n)
    frame["MARRIAGE"] = rng.integers(1, 4, n)
    frame["AGE"] = rng.integers(21, 70, n)
    frame["LIMIT_BAL"] = rng.integers(10, 500, n) * 1000.0
    logits = 0.9 * frame["PAY_0"] - 1.0 + 0.6 * (frame["SEX"] == 1)
    target = (rng.random(n) < 1 / (1 + np.exp(-logits))).astype(int).to_numpy()
    return frame, target


def test_age_group_bins():
    groups = fairness.age_group(pd.Series([21, 29, 30, 39, 40, 49, 50, 79]))
    assert groups.tolist() == ["<30", "<30", "30-39", "30-39", "40-49", "40-49", "50+", "50+"]


def test_sensitive_frame_maps_codes_to_labels():
    frame = pd.DataFrame({"SEX": [1, 2], "EDUCATION": [1, 0], "MARRIAGE": [2, 3], "AGE": [25, 45]})
    sensitive = fairness.sensitive_frame(frame)
    assert list(sensitive.columns) == list(fairness.SENSITIVE_ATTRIBUTES)
    assert sensitive.iloc[0].tolist() == ["male", "<30", "graduate_school", "single"]
    assert sensitive.iloc[1].tolist() == ["female", "40-49", "unknown", "others"]


def test_approval_decisions_match_serving_thresholds():
    decisions = fairness.approval_decisions(np.array([0.1, 0.3, 0.59, 0.6]), 0.3, 0.6)
    assert decisions.tolist() == ["APPROVE", "REVIEW", "REVIEW", "DECLINE"]


def test_audit_detects_disparity_by_hand():
    # Group a: all flagged; group b: none flagged -> DPD 1, approval gap 1, DI ratio 0.
    y_true = np.array([1, 0, 1, 0])
    y_prob = np.array([0.9, 0.8, 0.1, 0.2])
    sensitive = pd.Series(["a", "a", "b", "b"], name="grp")
    result = fairness.audit_attribute(y_true, y_prob, sensitive, threshold=0.5)
    summary = result["summary"]
    assert summary["demographic_parity_difference"] == pytest.approx(1.0)
    assert summary["equalized_odds_difference"] == pytest.approx(1.0)
    assert summary["disparate_impact_ratio"] == pytest.approx(0.0)
    assert result["status"] == "WARN"
    assert set(result["violations"]) == {
        "demographic_parity_difference",
        "equalized_odds_difference",
        "disparate_impact_ratio",
    }
    rows = {row["group"]: row for row in result["groups"]}
    assert rows["a"]["count"] == 2 and isinstance(rows["a"]["count"], int)
    assert rows["a"]["tpr"] == pytest.approx(1.0) and rows["a"]["fpr"] == pytest.approx(1.0)
    assert rows["b"]["approve_rate"] == pytest.approx(1.0)
    assert rows["a"]["decline_rate"] == pytest.approx(1.0)


def test_audit_passes_for_identical_groups():
    y_true = np.array([1, 0, 1, 0])
    y_prob = np.array([0.9, 0.1, 0.9, 0.1])
    result = fairness.audit_attribute(y_true, y_prob, pd.Series(["a", "a", "b", "b"], name="grp"))
    assert result["status"] == "PASS"
    assert result["summary"]["demographic_parity_difference"] == pytest.approx(0.0)
    assert result["summary"]["disparate_impact_ratio"] == pytest.approx(1.0)


def test_age_groups_are_ordered_chronologically():
    y_true = np.array([0, 1, 0, 1])
    y_prob = np.array([0.1, 0.9, 0.2, 0.8])
    result = fairness.audit_attribute(y_true, y_prob, pd.Series(["50+", "<30", "30-39", "40-49"], name="age_group"))
    assert [row["group"] for row in result["groups"]] == ["<30", "30-39", "40-49", "50+"]


def test_audit_fairness_covers_every_attribute():
    features, target = _cardholders()
    probs = np.clip(0.2 + 0.2 * features["PAY_0"].to_numpy(), 0, 1)
    report = fairness.audit_fairness(target, probs, fairness.sensitive_frame(features))
    assert set(report) == set(fairness.SENSITIVE_ATTRIBUTES)


def test_reweighing_makes_label_independent_of_group():
    sensitive = np.array(["a"] * 80 + ["b"] * 20)
    y = np.array([1] * 60 + [0] * 20 + [1] * 5 + [0] * 15)
    weights = fairness.reweighing_weights(y, sensitive)
    assert weights.mean() == pytest.approx(1.0)
    frame = pd.DataFrame({"a": sensitive, "y": y, "w": weights})
    weighted_rate = frame.groupby("a").apply(lambda g: np.average(g["y"], weights=g["w"]), include_groups=False)
    assert weighted_rate["a"] == pytest.approx(weighted_rate["b"])
    assert weighted_rate["a"] == pytest.approx(y.mean())


def test_neutralize_and_unaware_model_ignore_protected_columns():
    features, target = _cardholders()
    neutral = {"SEX": 2.0, "AGE": 37.0, "EDUCATION": 2.0, "MARRIAGE": 2.0}
    neutralized = fairness.neutralize_columns(features, neutral)
    assert (neutralized["SEX"] == 2.0).all() and (features["SEX"] != 2.0).any()

    unaware = fairness.make_unaware(Pipeline([("clf", LogisticRegression(max_iter=500))]), neutral)
    unaware.fit(features, target)
    flipped = features.assign(SEX=3 - features["SEX"], AGE=99)
    np.testing.assert_allclose(unaware.predict_proba(features), unaware.predict_proba(flipped))


def test_evaluate_variant_metrics():
    row = fairness.evaluate_variant(
        "v", [1, 0, 1, 0], [1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1], ["a", "a", "b", "b"], cost_fn=10, cost_fp=1
    )
    assert row["expected_loss"] == pytest.approx((10 + 1) / 4)
    assert row["demographic_parity_difference"] == pytest.approx(1.0)
    assert row["recall"] == pytest.approx(0.5)
    assert row["roc_auc"] == pytest.approx(0.75)


def test_run_mitigation_improves_fairness_with_threshold_optimizer():
    features, target = _cardholders(n=1200, seed=1)
    target_series = pd.Series(target, index=features.index)
    sensitive = fairness.sensitive_frame(features)["SEX"]

    def build() -> Pipeline:
        return Pipeline([("scaler", StandardScaler()), ("classifier", LogisticRegression(max_iter=1000))])

    champion = build().fit(features.iloc[:400], target_series.iloc[:400])
    data = fairness.MitigationData(
        x_train=features.iloc[:400],
        y_train=target_series.iloc[:400],
        x_fit=features.iloc[400:800],
        y_fit=target_series.iloc[400:800],
        sensitive_fit=sensitive.iloc[400:800],
        x_test=features.iloc[800:],
        y_test=target_series.iloc[800:],
        sensitive_test=sensitive.iloc[800:],
        sensitive_train=sensitive.iloc[:400],
    )
    rows = fairness.run_mitigation(
        champion, build, data, neutral_values={"SEX": 2.0, "AGE": 37.0, "EDUCATION": 2.0, "MARRIAGE": 2.0}
    )
    by_name = {row["variant"]: row for row in rows}
    assert list(by_name) == ["champion", "retrained", "reweighing", "unawareness", "threshold_optimizer"]
    assert (
        by_name["unawareness"]["demographic_parity_difference"] < by_name["champion"]["demographic_parity_difference"]
    )
    assert (
        by_name["threshold_optimizer"]["equalized_odds_difference"] < by_name["champion"]["equalized_odds_difference"]
    )
    for row in rows:
        assert 0.0 <= row["roc_auc"] <= 1.0
