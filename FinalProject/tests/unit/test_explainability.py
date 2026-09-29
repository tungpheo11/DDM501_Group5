import numpy as np
import pandas as pd
import pytest

from credit_risk.data.schema import ALL_FEATURES
from credit_risk.responsible_ai import explainability as xai


@pytest.fixture(scope="module")
def cardholders(settings) -> pd.DataFrame:
    frame = pd.read_csv(settings.paths.normal_stream)
    return frame[ALL_FEATURES].head(40).reset_index(drop=True)


def test_default_probability_fn_matches_model(champion_model, cardholders):
    predict = xai.default_probability_fn(champion_model)
    expected = champion_model.predict_proba(cardholders)[:, 1]
    np.testing.assert_allclose(predict(cardholders.to_numpy()), expected)
    np.testing.assert_allclose(predict(cardholders), expected)


def test_shap_explainer_is_additive_and_deterministic(champion_model, cardholders):
    explainer = xai.ShapExplainer(champion_model, cardholders.iloc[:10], max_evals=100, seed=7)
    rows = cardholders.iloc[10:13]
    first = explainer.explain(rows)
    second = explainer.explain(rows)
    np.testing.assert_allclose(first.values, second.values)
    reconstructed = first.values.sum(axis=1) + np.ravel(first.base_values)
    np.testing.assert_allclose(reconstructed, champion_model.predict_proba(rows)[:, 1], atol=1e-6)
    assert list(first.feature_names) == ALL_FEATURES


def test_shap_explainer_rejects_too_few_evals(champion_model, cardholders):
    with pytest.raises(ValueError, match="max_evals"):
        xai.ShapExplainer(champion_model, cardholders, max_evals=10)


def test_global_importance_and_local_contributions(champion_model, cardholders):
    explanation = xai.ShapExplainer(champion_model, cardholders.iloc[:10], max_evals=60).explain(
        cardholders.iloc[10:20]
    )
    importance = xai.global_importance(explanation)
    assert importance["mean_abs_shap"].is_monotonic_decreasing
    assert importance["share"].sum() == pytest.approx(1.0)
    local = xai.local_contributions(explanation, 0, top_k=5)
    assert len(local) == 5
    magnitudes = [abs(item["contribution"]) for item in local]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_explain_against_reference_base_is_reference_probability(champion_model, cardholders, settings):
    reference = settings.serving.explain_reference
    cardholder = cardholders.iloc[0].to_dict()
    result = xai.explain_against_reference(champion_model, cardholder, reference, ALL_FEATURES, max_evals=100)
    reference_frame = pd.DataFrame([reference])[ALL_FEATURES]
    assert result.reference_probability == pytest.approx(champion_model.predict_proba(reference_frame)[0, 1])
    assert result.probability == pytest.approx(champion_model.predict_proba(cardholders.iloc[[0]])[0, 1])
    assert sum(result.contributions.values()) == pytest.approx(result.probability - result.reference_probability)


def test_features_equal_to_reference_get_zero_attribution(champion_model, settings):
    reference = settings.serving.explain_reference
    cardholder = {**reference, "PAY_0": 3.0}
    result = xai.explain_against_reference(champion_model, cardholder, reference, ALL_FEATURES, max_evals=60)
    assert result.contributions["PAY_0"] == pytest.approx(result.probability - result.reference_probability)
    assert all(value == pytest.approx(0.0) for name, value in result.contributions.items() if name != "PAY_0")


def test_risk_factor_messages_put_risk_increasing_first():
    items = [
        {"feature": "LIMIT_BAL", "value": 20000.0, "contribution": -0.2},
        {"feature": "PAY_0", "value": 2.0, "contribution": 0.14},
        {"feature": "AGE", "value": 23.0, "contribution": 0.0},
    ]
    messages = xai.risk_factor_messages(items, limit=3)
    assert messages == [
        "PAY_0 = 2 (repayment status last month) increases default risk by +14.0 pp",
        "LIMIT_BAL = 20,000 NTD (credit limit) decreases default risk by -20.0 pp",
    ]


def test_lime_explain_and_agreement(champion_model, cardholders):
    items = xai.lime_explain(champion_model, cardholders, cardholders.iloc[0], num_features=5, num_samples=300, seed=3)
    assert len(items) == 5
    assert all(item["feature"] in ALL_FEATURES and item["feature"] in item["rule"] for item in items)
    again = xai.lime_explain(champion_model, cardholders, cardholders.iloc[0], num_features=5, num_samples=300, seed=3)
    assert items == again

    shap_items = [{"feature": item["feature"], "contribution": item["weight"]} for item in items]
    agreement = xai.rank_agreement(shap_items, items, k=5)
    assert agreement == {"k": 5, "overlap_at_k": 1.0, "sign_agreement": 1.0}


def test_rank_agreement_partial_overlap():
    shap_items = [{"feature": "A", "contribution": 0.3}, {"feature": "B", "contribution": -0.2}]
    lime_items = [{"feature": "B", "weight": 0.1}, {"feature": "C", "weight": 0.1}]
    assert xai.rank_agreement(shap_items, lime_items, k=2) == {"k": 2, "overlap_at_k": 0.5, "sign_agreement": 0.0}


def test_plots_are_written(champion_model, cardholders, tmp_path):
    explanation = xai.ShapExplainer(champion_model, cardholders.iloc[:5], max_evals=60).explain(cardholders.iloc[5:15])
    paths = [
        xai.plot_shap_summary(explanation, tmp_path / "summary.png"),
        xai.plot_shap_bar(explanation, tmp_path / "bar.png"),
        xai.plot_shap_waterfall(explanation[0], tmp_path / "waterfall.png", "t"),
        xai.plot_lime(
            [{"rule": "PAY_0 > 0", "weight": 0.2}, {"rule": "AGE <= 30", "weight": -0.1}], tmp_path / "l.png", "t"
        ),
    ]
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)
