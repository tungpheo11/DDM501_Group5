"""Data quality checks on the versioned datasets under data/."""

import pandas as pd
import pytest

from credit_risk.data.manifest import load_manifest, sha256_of
from credit_risk.data.schema import ALL_FEATURES, REQUEST_ID_COLUMN, TARGET_COLUMN

pytestmark = pytest.mark.data_quality


@pytest.fixture(scope="module")
def baseline(settings):
    return pd.read_csv(settings.paths.baseline_data)


def test_manifest_matches_files_on_disk(settings):
    manifest = load_manifest(settings.paths.data_manifest)
    assert manifest["files"], "data/manifest.json lists no files; run `make manifest`"
    for entry in manifest["files"]:
        path = settings.paths.data_dir / entry["path"]
        assert path.exists(), f"{entry['path']} listed in manifest but missing"
        assert sha256_of(path) == entry["sha256"], f"{entry['path']} changed; regenerate the manifest"


@pytest.mark.parametrize(
    ("attr", "rows"),
    [("raw_data", 30_000), ("baseline_data", 15_000), ("normal_stream", 5_000), ("drifted_stream", 5_000)],
)
def test_partition_sizes(settings, attr, rows):
    assert len(pd.read_csv(getattr(settings.paths, attr))) == rows


def test_baseline_schema_and_nulls(baseline):
    assert set(ALL_FEATURES + [TARGET_COLUMN]) <= set(baseline.columns)
    assert baseline[ALL_FEATURES + [TARGET_COLUMN]].isna().sum().sum() == 0


def test_value_domains(baseline):
    assert baseline[TARGET_COLUMN].isin([0, 1]).all()
    assert baseline["SEX"].isin([1, 2]).all()
    assert baseline["AGE"].between(18, 100).all()
    assert (baseline["LIMIT_BAL"] > 0).all()
    pay_cols = ["PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6"]
    assert baseline[pay_cols].isin(range(-2, 10)).all().all()


def test_target_rate_is_plausible(baseline):
    assert 0.15 <= baseline[TARGET_COLUMN].mean() <= 0.30


def test_cohort_design(settings, baseline):
    drifted = pd.read_csv(settings.paths.drifted_stream)
    assert baseline["AGE"].min() >= 30
    assert drifted["AGE"].max() < 30
    assert TARGET_COLUMN not in drifted.columns


def test_ground_truth_joins_drifted_stream(settings):
    drifted = pd.read_csv(settings.paths.drifted_stream)
    labels = pd.read_csv(settings.paths.ground_truth)
    assert drifted[REQUEST_ID_COLUMN].is_unique
    assert set(labels[REQUEST_ID_COLUMN]) == set(drifted[REQUEST_ID_COLUMN])
