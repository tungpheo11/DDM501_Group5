import numpy as np
import pandas as pd
import pytest

from credit_risk.data.schema import ALL_FEATURES, TARGET_COLUMN
from credit_risk.data.validation import (
    DataValidationError,
    build_engineered_schema,
    build_ground_truth_schema,
    build_labeled_schema,
    build_stream_schema,
    check_frame,
    validate_data_directory,
    validate_feature_frame,
    validate_frame,
    validate_training_frame,
)


@pytest.fixture(scope="module")
def labeled(settings):
    return pd.read_csv(settings.paths.baseline_data).head(500)


def test_versioned_datasets_pass_their_contracts(settings):
    reports = validate_data_directory(settings.paths.data_dir)
    assert {r.dataset for r in reports} == {
        "raw/credit_default.csv",
        "reference/train_baseline.csv",
        "processed/stream_normal.csv",
        "processed/stream_drifted.csv",
        "processed/ground_truth_feedback.csv",
    }
    assert all(r.passed for r in reports), [r.to_dict() for r in reports if not r.passed]


def test_training_frame_returns_features_and_target(labeled):
    validated = validate_training_frame(labeled)
    assert list(validated.columns) == ALL_FEATURES + [TARGET_COLUMN]


def test_feature_frame_ignores_extra_columns(labeled):
    frame = labeled.assign(request_id="x")
    assert list(validate_feature_frame(frame).columns) == ALL_FEATURES


@pytest.mark.parametrize(
    ("column", "value", "check"),
    [
        ("SEX", 3, "isin"),
        ("EDUCATION", 7, "isin"),
        ("AGE", 12, "in_range"),
        ("LIMIT_BAL", 0, "in_range"),
        ("PAY_0", 11, "in_range"),
        ("PAY_AMT1", -5, "in_range"),
    ],
)
def test_out_of_domain_values_fail_fast(labeled, column, value, check):
    dirty = labeled.copy()
    dirty.loc[dirty.index[0], column] = value
    with pytest.raises(DataValidationError) as excinfo:
        validate_training_frame(dirty, name="dirty")
    failure = excinfo.value.failures[0]
    assert failure["column"] == column
    assert check in failure["check"]
    assert "dirty" in str(excinfo.value)


def test_nulls_and_missing_columns_are_reported(labeled):
    dirty = labeled.drop(columns=["BILL_AMT3"])
    dirty.loc[dirty.index[1], "AGE"] = np.nan
    with pytest.raises(DataValidationError) as excinfo:
        validate_training_frame(dirty)
    columns = {f["column"] for f in excinfo.value.failures}
    assert "AGE" in columns
    assert excinfo.value.total_failures >= 2


def test_target_balance_check(labeled):
    all_negative = labeled.assign(**{TARGET_COLUMN: 0})
    report = check_frame(all_negative, build_labeled_schema("imbalanced"))
    assert not report.passed
    assert report.target_rate == 0.0
    assert any("target_balance" in f["check"] or "positive-class" in f["check"] for f in report.failures)


def test_stream_schema_requires_unique_request_ids(settings):
    stream = pd.read_csv(settings.paths.drifted_stream).head(50)
    stream.loc[1, "request_id"] = stream.loc[0, "request_id"]
    assert not check_frame(stream, build_stream_schema()).passed


def test_ground_truth_schema_is_strict():
    labels = pd.DataFrame({"request_id": ["a", "b"], TARGET_COLUMN: [0, 1], "extra": [1, 2]})
    assert not check_frame(labels, build_ground_truth_schema()).passed
    assert check_frame(labels.drop(columns=["extra"]), build_ground_truth_schema()).passed


def test_engineered_schema_rejects_non_finite_values():
    frame = pd.DataFrame({"ratio": [0.1, np.inf, 0.3]})
    with pytest.raises(DataValidationError):
        validate_frame(frame, build_engineered_schema(["ratio"]))
    validate_frame(frame.replace(np.inf, 1.0), build_engineered_schema(["ratio"]))


def test_report_serialises(labeled):
    payload = check_frame(labeled, build_labeled_schema("ok")).to_dict()
    assert payload["passed"] is True
    assert payload["rows"] == len(labeled)
    assert 0 < payload["target_rate"] < 1
