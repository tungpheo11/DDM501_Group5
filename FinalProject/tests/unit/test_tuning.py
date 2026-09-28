import pandas as pd
import pytest

from credit_risk.data.schema import ALL_FEATURES, TARGET_COLUMN
from credit_risk.training.models import CANDIDATES, class_balance_params, get_candidate
from credit_risk.training.pipeline import build_model_pipeline
from credit_risk.training.tuning import CostSettings, cross_validate_pipeline, tune_candidate


@pytest.fixture(scope="module")
def sample(settings):
    frame = pd.read_csv(settings.paths.baseline_data).head(900)
    return frame[ALL_FEATURES], frame[TARGET_COLUMN]


def test_candidate_catalogue_has_four_algorithms():
    assert set(CANDIDATES) == {"logistic_regression", "random_forest", "xgboost", "lightgbm"}
    assert get_candidate("RandomForestClassifier").name == "random_forest"
    with pytest.raises(KeyError):
        get_candidate("svm")


def test_class_balance_params_only_for_xgboost():
    assert class_balance_params("xgboost", [0, 0, 0, 1]) == {"scale_pos_weight": 3.0}
    assert class_balance_params("lightgbm", [0, 1]) == {}
    assert class_balance_params("xgboost", None) == {"scale_pos_weight": 1.0}


@pytest.mark.parametrize("name", sorted(CANDIDATES))
def test_every_candidate_builds_a_working_pipeline(sample, name):
    from credit_risk.training.models import LGBMClassifier, XGBClassifier

    if name == "lightgbm" and LGBMClassifier is None:
        pytest.skip("LightGBM is unavailable in this environment")
    if name == "xgboost" and XGBClassifier is None:
        pytest.skip("XGBoost is unavailable in this environment")
    features, target = sample
    pipeline = build_model_pipeline({}, random_state=0, model_name=name)
    pipeline.fit(features, target)
    assert pipeline.predict_proba(features.head(3)).shape == (3, 2)
    assert list(pipeline.named_steps) == ["features", "preprocessor", "classifier"]


def test_cross_validation_is_stratified_and_reports_business_metrics(sample):
    features, target = sample
    folds = []
    result = cross_validate_pipeline(
        "logistic_regression",
        {"C": 0.1},
        features,
        target,
        cv_folds=3,
        costs=CostSettings(threshold=0.5, cost_fn=10, cost_fp=1),
        on_fold=lambda fold, running: folds.append((fold, running)),
    )
    assert [f for f, _ in folds] == [0, 1, 2]
    assert len(result.fold_roc_auc) == 3
    assert result.oof_proba.shape == (len(target),)
    assert set(result.metrics) >= {"roc_auc_mean", "roc_auc_std", "pr_auc_mean", "oof_expected_loss"}
    assert 0.5 < result.metrics["roc_auc_mean"] < 1.0


def test_tuning_is_reproducible_with_fixed_seed(sample):
    features, target = sample
    first = tune_candidate("logistic_regression", features, target, n_trials=3, cv_folds=3, random_state=7)
    second = tune_candidate("logistic_regression", features, target, n_trials=3, cv_folds=3, random_state=7)
    assert first.best_params == second.best_params
    assert first.best_value == pytest.approx(second.best_value)
    assert first.n_trials == 3
    assert first.cv.metrics["roc_auc_mean"] == pytest.approx(first.best_value)


def test_tuning_invokes_trial_callback_and_injects_fixed_params(sample):
    from credit_risk.training.models import XGBClassifier

    if XGBClassifier is None:
        pytest.skip("XGBoost is unavailable in this environment")
    features, target = sample
    seen = []
    result = tune_candidate(
        "xgboost",
        features,
        target,
        n_trials=2,
        cv_folds=2,
        trial_callback=lambda study, trial: seen.append(trial.number),
    )
    assert seen == [0, 1]
    assert "scale_pos_weight" in result.best_params
    assert result.fixed_params == class_balance_params("xgboost", target.to_numpy())


def test_unsupported_metric_is_rejected(sample):
    with pytest.raises(ValueError, match="Unsupported tuning metric"):
        tune_candidate("logistic_regression", *sample, n_trials=1, metric="accuracy")
