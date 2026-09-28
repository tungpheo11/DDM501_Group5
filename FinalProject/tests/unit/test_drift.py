import json

import numpy as np
import pandas as pd
import pytest

from credit_risk.config import load_settings
from credit_risk.monitoring.drift import calculate_psi, classify_psi, load_inference_stream_from_db, run_drift_analysis


def test_psi_is_near_zero_for_same_distribution():
    rng = np.random.default_rng(0)
    series = pd.Series(rng.normal(size=5000))
    assert calculate_psi(series, series.sample(frac=1.0, random_state=1)) < 0.01


def test_psi_detects_shift():
    rng = np.random.default_rng(0)
    reference = pd.Series(rng.normal(40, 5, size=5000))
    current = pd.Series(rng.normal(25, 3, size=5000))
    assert calculate_psi(reference, current) >= 0.25


def test_psi_degenerate_inputs():
    assert calculate_psi(pd.Series([1.0] * 100), pd.Series([1.0] * 100)) == 0.0
    assert calculate_psi(pd.Series([], dtype=float), pd.Series([1.0])) == 0.0


@pytest.mark.parametrize(("value", "label"), [(0.05, "STABLE"), (0.10, "MODERATE"), (0.25, "CRITICAL")])
def test_classify_psi(value, label):
    assert classify_psi(value) == label


def test_db_stream_falls_back_when_unavailable(settings):
    assert load_inference_stream_from_db(settings) is None


def test_run_drift_analysis_detects_age_drift(tmp_path, monkeypatch, settings):
    baseline = pd.read_csv(settings.paths.baseline_data).head(800)
    drifted = pd.read_csv(settings.paths.drifted_stream).head(800)
    baseline.to_csv(tmp_path / "baseline.csv", index=False)
    drifted.to_csv(tmp_path / "drifted.csv", index=False)
    monkeypatch.setenv("BASELINE_DATA_PATH", str(tmp_path / "baseline.csv"))
    monkeypatch.setenv("DRIFTED_STREAM_PATH", str(tmp_path / "drifted.csv"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    result = run_drift_analysis(load_settings(env="test"))

    assert result.is_drifted is True
    assert result.psi["AGE"] >= 0.25
    assert (tmp_path / "reports" / "drift_report.html").exists()
    summary = json.loads((tmp_path / "reports" / "drift_summary.json").read_text())
    assert summary["psi_metrics"]["AGE"] == result.psi["AGE"]
