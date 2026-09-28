import numpy as np
import pandas as pd
import pytest

from credit_risk.data.schema import ALL_FEATURES, TARGET_COLUMN
from credit_risk.features.feature_engineering import (
    ENGINEERED_FEATURES,
    FeatureEngineer,
    add_engineered_features,
    engineer_features,
)
from credit_risk.features.preprocessing import create_feature_pipeline, create_preprocessor
from credit_risk.training.pipeline import build_model_pipeline


def _applicant(**overrides):
    row = dict.fromkeys(ALL_FEATURES, 0.0)
    row.update({"LIMIT_BAL": 100_000.0, "SEX": 2, "EDUCATION": 2, "MARRIAGE": 1, "AGE": 35})
    row.update(overrides)
    return pd.DataFrame([row])


def test_utilization_features():
    frame = _applicant(
        BILL_AMT1=50_000, BILL_AMT2=40_000, BILL_AMT3=30_000, BILL_AMT4=20_000, BILL_AMT5=10_000, BILL_AMT6=0
    )
    features = engineer_features(frame).iloc[0]
    assert features["utilization_latest"] == pytest.approx(0.5)
    assert features["utilization_mean"] == pytest.approx(0.25)
    assert features["utilization_max"] == pytest.approx(0.5)
    assert features["utilization_trend"] == pytest.approx(0.1)


def test_payment_ratio_pairs_payment_with_previous_statement():
    frame = _applicant(BILL_AMT2=10_000, PAY_AMT1=2_500, BILL_AMT3=10_000, PAY_AMT2=10_000)
    features = engineer_features(frame).iloc[0]
    assert features["payment_ratio_latest"] == pytest.approx(0.25)
    assert features["payment_ratio_mean"] == pytest.approx(12_500 / 20_000)


def test_payment_ratio_without_debt_is_fully_paid_and_bounded():
    no_debt = engineer_features(_applicant()).iloc[0]
    assert no_debt["payment_ratio_latest"] == 1.0
    assert no_debt["payment_ratio_mean"] == 1.0
    overpaid = engineer_features(_applicant(BILL_AMT2=100, PAY_AMT1=1_000_000)).iloc[0]
    assert overpaid["payment_ratio_latest"] == 5.0


def test_delay_features_capture_worsening_behaviour():
    worsening = _applicant(PAY_6=-1, PAY_5=0, PAY_4=0, PAY_3=1, PAY_2=2, PAY_0=3)
    improving = _applicant(PAY_6=3, PAY_5=2, PAY_4=1, PAY_3=0, PAY_2=0, PAY_0=-1)
    worse, better = engineer_features(worsening).iloc[0], engineer_features(improving).iloc[0]
    assert worse["delay_trend"] > 0 > better["delay_trend"]
    assert worse["delay_max"] == 3
    assert worse["delay_months"] == 3
    assert worse["delay_recent_mean"] == pytest.approx(2.0)


def test_zero_payment_months_and_pay_to_limit():
    features = engineer_features(_applicant(PAY_AMT1=6_000, PAY_AMT2=6_000)).iloc[0]
    assert features["zero_payment_months"] == 4
    assert features["pay_to_limit_ratio"] == pytest.approx(2_000 / 100_000)


def test_real_data_produces_finite_engineered_features(settings):
    frame = pd.read_csv(settings.paths.baseline_data)
    engineered = engineer_features(frame)
    assert list(engineered.columns) == ENGINEERED_FEATURES
    assert np.isfinite(engineered.to_numpy()).all()


def test_add_engineered_features_preserves_index_and_order():
    frame = pd.concat([_applicant(), _applicant(AGE=50)], ignore_index=True)
    frame.index = [10, 20]
    combined = add_engineered_features(frame)
    assert list(combined.index) == [10, 20]
    assert list(combined.columns) == ALL_FEATURES + ENGINEERED_FEATURES


def test_feature_engineer_is_stateless_transformer():
    engineer = FeatureEngineer()
    frame = _applicant(BILL_AMT1=10_000)
    assert engineer.fit(frame) is engineer
    transformed = engineer.transform(frame)
    assert list(engineer.get_feature_names_out()) == list(transformed.columns)
    from_array = engineer.transform(frame[ALL_FEATURES].to_numpy())
    pd.testing.assert_frame_equal(transformed.reset_index(drop=True), from_array, check_dtype=False)


def test_pipeline_exposes_training_input_schema(settings):
    from credit_risk.training.pipeline import build_model_pipeline

    frame = pd.read_csv(settings.paths.normal_stream).head(300)
    pipeline = build_model_pipeline({"max_iter": 500}, 42, model_name="logistic_regression")
    pipeline.fit(frame[ALL_FEATURES], frame[TARGET_COLUMN])
    assert list(pipeline.feature_names_in_) == ALL_FEATURES
    assert pipeline.n_features_in_ == len(ALL_FEATURES)


def test_feature_pipeline_output_width(settings):
    frame = pd.read_csv(settings.paths.normal_stream).head(200)
    matrix = create_feature_pipeline().fit_transform(frame)
    assert matrix.shape[0] == 200
    assert matrix.shape[1] > len(ALL_FEATURES) + len(ENGINEERED_FEATURES) - 3


def test_legacy_preprocessor_without_engineered_features(settings):
    frame = pd.read_csv(settings.paths.normal_stream).head(50)
    assert create_preprocessor(include_engineered=False).fit_transform(frame[ALL_FEATURES]).shape[0] == 50


def test_train_serve_parity(settings):
    """A single serving-style row must score exactly as the same row inside a training batch."""
    frame = pd.read_csv(settings.paths.baseline_data).head(400)
    pipeline = build_model_pipeline({"C": 0.5}, random_state=42, model_name="logistic_regression")
    pipeline.fit(frame[ALL_FEATURES], frame["default_payment_next_month"])
    batch = pipeline.predict_proba(frame[ALL_FEATURES])[:, 1]
    single = pipeline.predict_proba(pd.DataFrame([frame[ALL_FEATURES].iloc[7].to_dict()]))[:, 1]
    assert single[0] == pytest.approx(batch[7])
