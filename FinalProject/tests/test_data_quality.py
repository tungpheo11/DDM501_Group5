"""
Data Quality and Schema Validation Tests for Credit Default Datasets.
Verifies domain boundaries, missingness, duplicates, and distributions.
"""

from pathlib import Path
import pandas as pd

from src.config import (
    BASELINE_DATA_PATH,
    NORMAL_STREAM_PATH,
    DRIFTED_STREAM_PATH,
    ALL_FEATURES,
    TARGET_COLUMN,
)


def test_baseline_dataset_integrity():
    """Verify baseline dataset exists, is non-empty, and has no missing values."""
    path = Path(BASELINE_DATA_PATH)
    assert path.exists(), f"Baseline dataset not found at {path}"

    df = pd.read_csv(path)
    assert len(df) >= 1000, f"Expected at least 1,000 baseline records, found {len(df)}"

    # Ensure all 23 features + target exist
    for feat in ALL_FEATURES:
        assert feat in df.columns, f"Missing feature in baseline: {feat}"
    assert TARGET_COLUMN in df.columns, f"Missing target column: {TARGET_COLUMN}"

    # Missing value assertion (Zero nulls allowed)
    null_counts = df[ALL_FEATURES + [TARGET_COLUMN]].isnull().sum().sum()
    assert null_counts == 0, f"Baseline dataset contains {null_counts} missing values!"


def test_domain_boundaries_financial():
    """Verify financial and demographic domain boundaries on baseline data."""
    df = pd.read_csv(BASELINE_DATA_PATH)

    # 1. LIMIT_BAL must be strictly positive
    assert (df["LIMIT_BAL"] > 0).all(), "Found non-positive credit limits in LIMIT_BAL!"

    # 2. AGE must be legal working adult (>= 18 and <= 100)
    assert (df["AGE"] >= 18).all(), "Found minor applicants with AGE < 18!"
    assert (df["AGE"] <= 100).all(), "Found unrealistic AGE > 100!"

    # 3. Categorical ranges
    assert df["SEX"].isin([1, 2]).all(), "SEX must only contain 1 (Male) or 2 (Female)"
    assert (
        df["EDUCATION"].isin([0, 1, 2, 3, 4, 5, 6]).all()
    ), "EDUCATION contains out-of-range categorical codes"
    assert (
        df["MARRIAGE"].isin([0, 1, 2, 3]).all()
    ), "MARRIAGE contains out-of-range categorical codes"

    # 4. Target variable must be binary (0 or 1)
    assert df[TARGET_COLUMN].isin([0, 1]).all(), "Target variable must be strictly {0, 1}"


def test_target_class_distribution():
    """Verify realistic default class imbalance (15% to 30% positive default rate)."""
    df = pd.read_csv(BASELINE_DATA_PATH)
    default_rate = df[TARGET_COLUMN].mean()
    assert 0.15 <= default_rate <= 0.35, f"Unexpected default rate: {default_rate:.2%}"


def test_stream_datasets_exist():
    """Verify normal and drifted production simulation data streams exist."""
    assert Path(NORMAL_STREAM_PATH).exists()
    assert Path(DRIFTED_STREAM_PATH).exists()

    df_normal = pd.read_csv(NORMAL_STREAM_PATH)
    df_drifted = pd.read_csv(DRIFTED_STREAM_PATH)

    assert len(df_normal) > 0
    assert len(df_drifted) > 0
    assert (df_drifted["AGE"] < df_normal["AGE"].mean()).mean() > 0.5
