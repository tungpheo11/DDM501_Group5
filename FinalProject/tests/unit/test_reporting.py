import json

import pytest

from credit_risk.training import reporting


@pytest.fixture
def report():
    metrics = {"roc_auc": 0.77, "pr_auc": 0.55, "f1_score": 0.52, "recall": 0.6, "expected_loss": 1.05}
    cv = {"roc_auc_mean": 0.751, "roc_auc_std": 0.012, "cost_optimal_threshold": 0.22}
    model = {
        "best_params": {"C": 0.03},
        "cv": cv,
        "holdout": metrics,
        "normal_stream": metrics,
        "tuning": {"n_trials": 20, "n_pruned": 3, "best_trial": 7, "duration_seconds": 4.2},
        "mlflow_run_id": "abc",
    }
    return {
        "generated_at": "2026-09-28T00:00:00+00:00",
        "session_id": "20260928T000000Z",
        "selected_model": "logistic_regression",
        "config": {
            "test_size": 0.2,
            "cv_folds": 5,
            "random_state": 42,
            "n_trials": 20,
            "metric": "roc_auc",
            "decision_threshold": 0.5,
            "cost_false_negative": 10.0,
            "cost_false_positive": 1.0,
            "n_engineered_features": 12,
        },
        "data": {
            "train_file": "reference/train_baseline.csv",
            "gate_file": "processed/stream_normal.csv",
            "train_rows": 12000,
            "holdout_rows": 3000,
            "gate_rows": 5000,
            "data_version": "abcd",
            "manifest_verified": True,
        },
        "models": [
            {"name": "logistic_regression", "display_name": "Logistic Regression", **model},
            {"name": "lightgbm", "display_name": "LightGBM", **model},
        ],
        "gate": {"promote": True, "reasons": ["no current champion; challenger passes the quality floor"]},
        "registry": {"model_name": "credit-risk-model", "registered_version": "3", "champion_version": "3"},
    }


def test_markdown_report_contains_every_model_and_gate(report, tmp_path):
    path = reporting.write_markdown_report(report, tmp_path / "model_comparison.md")
    text = path.read_text()
    assert "**Logistic Regression** (selected)" in text
    assert "| LightGBM |" in text
    assert "PROMOTE" in text
    assert "version **3**" in text
    assert "0.7510 ± 0.0120" in text


def test_json_report_roundtrip(report, tmp_path):
    path = reporting.write_json_report(report, tmp_path / "out" / "model_comparison.json")
    assert json.loads(path.read_text()) == report


def test_readme_block_is_replaced_between_markers(report, tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"# Title\n\n{reporting.README_START}\nold numbers 0.760\n{reporting.README_END}\n\nFooter\n")
    assert reporting.sync_readme(report, readme)
    text = readme.read_text()
    assert "old numbers" not in text
    assert "0.7700" in text and text.endswith("Footer\n")
    assert text.count(reporting.README_START) == 1


def test_readme_without_markers_is_left_untouched(report, tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n")
    assert not reporting.sync_readme(report, readme)
    assert readme.read_text() == "# Title\n"
    assert not reporting.sync_readme(report, tmp_path / "missing.md")
